"""Incremental update for mnemosyne update command."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mnemosyne.ingest.ingester import Ingester, IngestResult, result_to_dict
from mnemosyne.ingest.llm_extractor import is_supported_file

logger = logging.getLogger(__name__)


@dataclass
class UpdateStats:
    """Aggregated stats for an incremental update run."""

    total: int = 0
    changed: int = 0
    new_files: int = 0
    unchanged: int = 0
    errors: int = 0
    pruned: int = 0
    results: list[IngestResult] = field(default_factory=list)


# @MX:ANCHOR: [AUTO] Updater is the public incremental-update entry point.
# @MX:REASON: Called by CLI and library users; fan_in >= 3 in pipeline orchestration.
class Updater:
    """Re-extract changed files since the last successful ingestion."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        raw_root: Optional[Path] = None,
        wiki_root: Optional[Path] = None,
        include_wiki_excerpts: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.db_path = db_path
        self.raw_root = raw_root or (Path.home() / "mnemosyne" / "raw")
        self.wiki_root = wiki_root
        self.include_wiki_excerpts = include_wiki_excerpts
        self.dry_run = dry_run

    def update(
        self,
        path: Optional[Path] = None,
        domain: Optional[str] = None,
        scope_id: Optional[str] = None,
        source_channel: str = "cli",
        prune: bool = False,
    ) -> UpdateStats:
        """Walk ``path`` (default: ``raw_root``) and re-extract changed files."""
        scan_root = path.expanduser() if path else self.raw_root
        scan_root.mkdir(parents=True, exist_ok=True)

        ingester = Ingester(
            db_path=self.db_path,
            raw_root=self.raw_root,
            wiki_root=self.wiki_root,
            include_wiki_excerpts=self.include_wiki_excerpts,
            dry_run=self.dry_run,
        )
        stats = UpdateStats()
        try:
            kg = ingester._get_kg()  # noqa: SLF001 -- intentional internal access
            cache = self._load_cache(kg.conn)

            for file_path in self._iter_files(scan_root):
                stats.total += 1
                resolved = str(file_path)
                content_hash = self._hash_file(file_path)

                cached = cache.get(resolved)
                if cached == content_hash:
                    stats.unchanged += 1
                    continue

                resolved_domain = domain or self._infer_domain(file_path)

                try:
                    result = ingester._add_file(  # noqa: SLF001
                        file_path,
                        domain=resolved_domain,
                        scope_id=scope_id,
                        source_channel=source_channel,
                    )
                except (OSError, sqlite3.Error, ValueError) as exc:
                    stats.errors += 1
                    stats.results.append(
                        IngestResult(source=resolved, errors=[str(exc)])
                    )
                    logger.error("Update failed for %s: %s", file_path, exc)
                    continue

                stats.results.append(result)
                if result.errors:
                    stats.errors += 1
                if cached is None:
                    stats.new_files += 1
                else:
                    stats.changed += 1

            if prune:
                stats.pruned = self._prune(kg.conn, cache)
        finally:
            ingester.close()

        return stats

    def stats_only(self, path: Optional[Path] = None) -> UpdateStats:
        """Compute change stats without performing extraction."""
        scan_root = path.expanduser() if path else self.raw_root
        scan_root.mkdir(parents=True, exist_ok=True)

        ingester = Ingester(
            db_path=self.db_path,
            raw_root=self.raw_root,
            wiki_root=None,
            dry_run=True,
        )
        stats = UpdateStats()
        try:
            kg = ingester._get_kg()  # noqa: SLF001
            cache = self._load_cache(kg.conn)
            for file_path in self._iter_files(scan_root):
                stats.total += 1
                content_hash = self._hash_file(file_path)
                cached = cache.get(str(file_path))
                if cached is None:
                    stats.new_files += 1
                elif cached != content_hash:
                    stats.changed += 1
                else:
                    stats.unchanged += 1
        finally:
            ingester.close()
        return stats

    @staticmethod
    def _iter_files(root: Path) -> list[Path]:
        out: list[Path] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            if not is_supported_file(p):
                continue
            out.append(p)
        return out

    @staticmethod
    def _infer_domain(path: Path) -> str:
        # Path layout: raw/<domain>/...
        parts = [p.lower() for p in path.parts]
        for known in ("coding", "daily", "legal"):
            if known in parts:
                return known
        return "daily"

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _load_cache(conn: sqlite3.Connection) -> dict[str, str]:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_cache (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        rows = conn.execute(
            "SELECT file_path, content_hash FROM ingest_cache"
        ).fetchall()
        return {row["file_path"]: row["content_hash"] for row in rows}

    @staticmethod
    def _prune(conn: sqlite3.Connection, cache: dict[str, str]) -> int:
        # @MX:NOTE: [AUTO] Prune only removes cache entries; entity removal is v2.
        removed = 0
        for file_path in list(cache.keys()):
            if not Path(file_path).exists():
                conn.execute(
                    "DELETE FROM ingest_cache WHERE file_path = ?", (file_path,)
                )
                removed += 1
        if removed:
            conn.commit()
        return removed


def stats_to_dict(stats: UpdateStats) -> dict[str, Any]:
    """Serialize :class:`UpdateStats` to a JSON-friendly dict."""
    return {
        "total": stats.total,
        "changed": stats.changed,
        "new_files": stats.new_files,
        "unchanged": stats.unchanged,
        "errors": stats.errors,
        "pruned": stats.pruned,
        "results": [result_to_dict(r) for r in stats.results],
    }
