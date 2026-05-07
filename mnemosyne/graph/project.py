"""Project detection and registration for scope-aware knowledge graphs."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_MARKERS = (
    ".git",
    ".mnemosyne",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
)


def detect_project(start: Optional[Path] = None) -> Optional[Tuple[Path, str]]:
    """Walk up from *start* (defaults to CWD) to find a project root.

    Returns ``(project_path, project_hash)`` where *project_hash* is the
    SHA-256 hex digest of the canonical path string, or ``None`` if no
    project marker is found.
    """
    current = (start or Path.cwd()).resolve()

    while True:
        for marker in _PROJECT_MARKERS:
            if (current / marker).exists():
                canonical = str(current)
                project_hash = hashlib.sha256(canonical.encode()).hexdigest()
                return current, project_hash

        parent = current.parent
        if parent == current:
            return None
        current = parent


def resolve_scope_id(
    kg,
    start: Optional[Path] = None,
    explicit_scope_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve the effective scope_id for the current project context.

    Priority:
    1. *explicit_scope_id* (``--scope-id`` override) always wins.
    2. Auto-detected project scope from the ``projects`` table.
    3. ``None`` (global scope) if no project found.

    When a project is detected but not yet registered, it is auto-registered.
    """
    if explicit_scope_id is not None:
        return explicit_scope_id

    result = detect_project(start)
    if result is None:
        return None

    project_path, project_hash = result
    existing = kg.get_project_by_hash(project_hash)
    if existing:
        return existing["scope_id"]

    project_name = project_path.name
    scope_id = kg.register_project(
        project_hash=project_hash,
        project_name=project_name,
        project_path=str(project_path),
    )
    logger.info("Auto-registered project %s", project_name)
    return scope_id
