"""Recover the disposable wiki from a committed, visibility-filtered graph.

A generation is published through one atomic index replacement. No original
source is read, and no existing wiki content is reused as answer evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from mnemosyne.graph.lifecycle import LifecycleError, LifecycleStore
from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer


def _database_key(kg):
    return hashlib.sha256(str(kg.db_path.resolve()).encode()).hexdigest()


def _publish_snapshot(source: Path, destination: Path) -> None:
    if os.name == "nt":
        # Windows cannot open/fsync a directory through os.open. Ask the native
        # same-volume rename API to finish its write before clearing wiki_dirty.
        import ctypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH; never copy/delete.
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def rebuild_wiki(kg, wiki_root) -> dict:
    root = Path(wiki_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = LifecycleStore(kg)
    # Publication shares SQLite's writer transaction with graph mutations.
    # Unlike an O_EXCL lock file, it is released by the OS after a hard crash.
    with store.lock:
        # Failure at any subsequent filesystem step must remain recoverable.
        with store._transaction():
            if store.status()["generation"] == 0:
                store._bump()
            kg.conn.execute("UPDATE lifecycle_state SET wiki_dirty=1 WHERE id=1")
        with store.lock:
            kg.conn.execute("BEGIN")
            try:
                generation = store.status()["generation"]
                from mnemosyne.graph.knowledge_graph import _isolation_clause, _ISOLATION_PARAMS

                entities = [
                    dict(r)
                    for r in kg.conn.execute(
                        f"SELECT * FROM entities WHERE {_isolation_clause()} ORDER BY type,name,id",
                        _ISOLATION_PARAMS,
                    )
                ]
                relations = [
                    dict(r)
                    for r in kg.conn.execute(
                        f"SELECT * FROM relations WHERE {_isolation_clause()} ORDER BY id",
                        _ISOLATION_PARAMS,
                    )
                ]
            finally:
                kg.conn.rollback()
        # A single snapshot document avoids old source pages accumulating facts
        # and lets the manifest and all its claims change atomically together.
        lines = [
            "---",
            "page_type: lifecycle-index",
            f"graph_generation: {generation}",
            f"graph_database: {_database_key(kg)}",
            "---",
            "",
            "# Mnemosyne current knowledge",
            "",
            "<!-- MNEMOSYNE:GENERATED:START -->",
            "",
            "This is a derived snapshot, not an independent source. Validate graph_generation",
            "against the database before retrieval. Use graph queries while wiki_dirty is true.",
            "",
            "User notes, corrections and visibility records are canonical in SQLite.",
            "",
        ]
        visible = {r["id"] for r in entities}
        for row in entities:
            lines.extend(
                [
                    f"## {row['name']}",
                    "",
                    "```json",
                    json.dumps(
                        {**row, "properties": json.loads(row["properties"] or "{}")},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "## Relations",
                "",
                "```json",
                json.dumps(
                    [
                        {**row, "properties": json.loads(row["properties"] or "{}")}
                        for row in relations
                        if row["source_id"] in visible and row["target_id"] in visible
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "<!-- MNEMOSYNE:GENERATED:END -->",
                "",
            ]
        )
        stage = Path(tempfile.mkdtemp(prefix=".lifecycle-build-", dir=root))
        try:
            LLMWikiMaintainer._atomic_write(stage / "index.md", "\n".join(lines))
            with (stage / "index.md").open("rb+") as snapshot:
                os.fsync(snapshot.fileno())
            with store._transaction():
                if store.status()["generation"] != generation:
                    raise LifecycleError("graph changed during wiki generation; rebuild again")
                # Retire old generated pages, including manual notes, without
                # destroying them. They are history, never the current index.
                retired = []
                old_index = root / "index.md"
                if old_index.exists():
                    header = old_index.read_text(encoding="utf-8").split("---", 2)
                    if (
                        len(header) < 3
                        or "page_type: lifecycle-index" not in header[1].splitlines()
                    ):
                        retired.append(old_index)
                for dirname in ("entities", "sources"):
                    for path in (root / dirname).rglob("*.md"):
                        if "<!-- MNEMOSYNE:GENERATED:START -->" in path.read_text(encoding="utf-8"):
                            retired.append(path)
                for path in retired:
                    destination = root / ".lifecycle-history" / stage.name / path.relative_to(root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(path, destination)
                _publish_snapshot(stage / "index.md", root / "index.md")
                kg.conn.execute("UPDATE lifecycle_state SET wiki_dirty=0 WHERE id=1")
            return {
                "status": "rebuilt",
                "generation": generation,
                "wiki_dirty": False,
                "paths": [str(root / "index.md")],
                "entities": len(entities),
                "relations": sum(
                    r["source_id"] in visible and r["target_id"] in visible for r in relations
                ),
            }
        finally:
            shutil.rmtree(stage)


def read_current_wiki(kg, wiki_root) -> str:
    """Fail closed for answer consumers; a stale Markdown file is not evidence."""
    with LifecycleStore(kg).lock:
        kg.conn.execute("BEGIN")
        try:
            state = LifecycleStore(kg).status()
            if state["wiki_dirty"]:
                raise LifecycleError("wiki is dirty; query the graph or rebuild")
            text = (Path(wiki_root).expanduser() / "index.md").read_text(encoding="utf-8")
            header = text.split("---", 2)
            expected = {
                f"graph_generation: {state['generation']}",
                f"graph_database: {_database_key(kg)}",
            }
            if len(header) < 3 or not expected.issubset(header[1].splitlines()):
                raise LifecycleError("wiki database or generation does not match graph")
            return text
        finally:
            kg.conn.rollback()
