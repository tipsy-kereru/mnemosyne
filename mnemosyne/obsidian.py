"""Safe, local-only synchronization of an Obsidian vault.

The vault is an input boundary, not a Mnemosyne storage root.  This module
keeps the personal SQLite database and raw cache outside the vault and skips
Obsidian metadata plus generated Wiki content before the incremental updater
sees any files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from mnemosyne.ingest.ingester import IngestResult, Ingester
from mnemosyne.ingest.llm_extractor import is_supported_file
from mnemosyne.ingest.update import UpdateStats, Updater

DEFAULT_WIKI_DIR = "_MnemosyneWiki"
DEFAULT_EXCLUDED_DIRS = (".obsidian", ".trash", DEFAULT_WIKI_DIR)


class ObsidianSyncError(ValueError):
    """Raised when a vault or storage boundary is unsafe."""


@dataclass(frozen=True)
class ObsidianSyncConfig:
    """Explicit paths and policy for one local vault sync."""

    vault_root: Path
    db_path: Path
    raw_root: Path
    wiki_root: Path | None = None
    scope_id: str = "personal"
    source_channel: str = "obsidian"
    domain: str = "auto"
    prune: bool = False
    dry_run: bool = False
    include_wiki_excerpts: bool = False
    exclude_dirs: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ObsidianSyncConfig":
        vault_root = self.vault_root.expanduser().resolve()
        if not vault_root.is_dir():
            raise ObsidianSyncError(f"vault root is not a directory: {vault_root}")

        db_path = self.db_path.expanduser().resolve()
        raw_root = self.raw_root.expanduser().resolve()
        if _is_within(db_path, vault_root):
            raise ObsidianSyncError("db-path must be outside the Obsidian vault")
        if _is_within(raw_root, vault_root):
            raise ObsidianSyncError("raw-root must be outside the Obsidian vault")

        wiki_root = (self.wiki_root or vault_root / DEFAULT_WIKI_DIR).expanduser().resolve()
        if not self.scope_id.strip():
            raise ObsidianSyncError("scope-id must not be empty")
        if not self.source_channel.strip():
            raise ObsidianSyncError("source-channel must not be empty")
        if self.domain not in {"auto", "coding", "daily", "legal"}:
            raise ObsidianSyncError(f"unsupported domain: {self.domain}")

        extra = tuple(item for item in self.exclude_dirs if item.strip())
        return ObsidianSyncConfig(
            vault_root=vault_root,
            db_path=db_path,
            raw_root=raw_root,
            wiki_root=wiki_root,
            scope_id=self.scope_id.strip(),
            source_channel=self.source_channel.strip(),
            domain=self.domain,
            prune=self.prune,
            dry_run=self.dry_run,
            include_wiki_excerpts=self.include_wiki_excerpts,
            exclude_dirs=extra,
        )


def sync_vault(config: ObsidianSyncConfig) -> UpdateStats:
    """Incrementally ingest supported files from a validated vault."""

    config = config.normalized()
    updater = Updater(
        db_path=config.db_path,
        raw_root=config.raw_root,
        wiki_root=config.wiki_root,
        include_wiki_excerpts=config.include_wiki_excerpts,
        dry_run=config.dry_run,
        exclude_paths=_excluded_paths(config),
    )
    return updater.update(
        path=config.vault_root,
        domain=None if config.domain == "auto" else config.domain,
        scope_id=config.scope_id,
        source_channel=config.source_channel,
        prune=config.prune,
    )


def sync_file(config: ObsidianSyncConfig, file_path: Path) -> IngestResult:
    """Ingest one supported file after applying the Vault boundary policy."""

    config = config.normalized()
    candidate = file_path.expanduser().resolve()
    if not _is_within(candidate, config.vault_root):
        raise ObsidianSyncError("file must be inside the Obsidian vault")
    if any(
        candidate == excluded or excluded in candidate.parents
        for excluded in _excluded_paths(config)
    ):
        raise ObsidianSyncError("file is inside an excluded Obsidian directory")
    if not candidate.is_file():
        raise ObsidianSyncError(f"file is not present: {candidate}")
    if not is_supported_file(candidate):
        raise ObsidianSyncError(f"unsupported file type: {candidate.suffix}")

    resolved_domain = (
        Updater._infer_domain(candidate) if config.domain == "auto" else config.domain
    )
    ingester = Ingester(
        db_path=config.db_path,
        raw_root=config.raw_root,
        wiki_root=config.wiki_root,
        include_wiki_excerpts=config.include_wiki_excerpts,
        dry_run=config.dry_run,
    )
    try:
        return ingester.add(
            target=str(candidate),
            domain=resolved_domain,
            scope_id=config.scope_id,
            source_channel=config.source_channel,
        )
    finally:
        ingester.close()


def inspect_vault(config: ObsidianSyncConfig) -> UpdateStats:
    """Return hash-based change counts without extraction or graph/Wiki writes."""

    config = config.normalized()
    updater = Updater(
        db_path=config.db_path,
        raw_root=config.raw_root,
        wiki_root=None,
        dry_run=True,
        exclude_paths=_excluded_paths(config),
    )
    return updater.stats_only(path=config.vault_root)


def _excluded_paths(config: ObsidianSyncConfig) -> list[Path]:
    paths = [config.vault_root / name for name in DEFAULT_EXCLUDED_DIRS]
    paths.extend(_resolve_exclude(config.vault_root, name) for name in config.exclude_dirs)
    if _is_within(config.wiki_root, config.vault_root):
        paths.append(config.wiki_root)
    return _unique_paths(paths)


def _resolve_exclude(vault_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (vault_root / path).resolve()


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
