"""SPEC-LONGDOC-001 REQ-LD-008 (partial): path-traversal guard.

Shared validator used by ``LongDocIndexer`` to reject file paths that escape
the raw directory: ``..`` segments or absolute paths not nested under the
configured raw root. Full security review (memory bounds, >1000-page reject)
lands in the mandatory REVIEW phase per SPEC-LONGDOC-001 §10.
"""

from __future__ import annotations

from pathlib import Path


class LongDocPathError(ValueError):
    """Raised when a long-doc source path fails the traversal guard."""


def validate_longdoc_path(path: "str | Path", raw_root: "str | Path") -> Path:
    """Validate that *path* resolves inside *raw_root*.

    Returns the resolved ``Path``. Raises ``LongDocPathError`` on:
        - any ``..`` segment in the input (before resolution)
        - the input being absolute AND not under *raw_root*
        - the resolved real path escaping *raw_root* after symlink expansion

    REQ-LD-008 partial. The full streaming / OOM hardening is REVIEW-phase.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(raw_root, Path):
        raw_root = Path(raw_root)

    # Cheap lexical guard: reject explicit parent-segment escapes regardless
    # of how they resolve. ``os.path.normpath`` collapses them; we inspect the
    # raw parts so an attempt is never silently normalised away.
    for part in path.parts:
        if part == "..":
            raise LongDocPathError(
                f"Rejected long-doc path containing '..': {path}"
            )

    # Absolute paths must be anchored under raw_root.
    if path.is_absolute():
        try:
            resolved_root = raw_root.resolve()
        except OSError:
            resolved_root = raw_root
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise LongDocPathError(
                f"Cannot resolve long-doc path {path}: {exc}"
            ) from exc
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise LongDocPathError(
                f"Long-doc path {path} is outside raw root {raw_root}"
            ) from exc
        return resolved

    # Relative paths are taken as raw-root-relative.
    return raw_root / path
