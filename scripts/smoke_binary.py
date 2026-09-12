"""Exercise a relocated release executable without Python/toolchain paths."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def smoke(binary: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="mnemosyne-binary-smoke-") as temporary:
        root = Path(temporary)
        environment = {**os.environ, "HOME": temporary, "USERPROFILE": temporary}
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        if os.name == "nt":
            windows = Path(os.environ["SystemRoot"])
            environment["PATH"] = os.pathsep.join(map(str, [windows / "System32", windows]))
        else:
            environment["PATH"] = "/usr/bin:/bin"

        def run(*arguments, request=None, expected=0):
            result = subprocess.run(
                [str(binary), *map(str, arguments)],
                input=None if request is None else json.dumps(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=root,
                env=environment,
                timeout=60,
            )
            if result.returncode != expected:
                raise RuntimeError(
                    f"{arguments}: exit {result.returncode}, expected {expected}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            return result.stdout.strip()

        actual_version = run("--version")
        assert actual_version == f"mnemosyne {version}", actual_version
        run("--help")
        run(
            "-c",
            "import socket, ssl, sqlite3, hashlib, ctypes, mnemosyne_core; "
            "import mcp.server.fastmcp; "
            "ssl.create_default_context(); "
            "s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
            "s.settimeout(5); s.bind(('127.0.0.1', 0)); "
            "s.sendto(b'packaged-socket', s.getsockname()); "
            "assert s.recv(64)==b'packaged-socket'; s.close(); "
            "db=sqlite3.connect(':memory:'); "
            "db.execute('CREATE VIRTUAL TABLE smoke USING fts5(text)'); "
            "db.execute(\"INSERT INTO smoke VALUES ('packaged sqlite')\"); "
            "assert db.execute(\"SELECT count(*) FROM smoke WHERE smoke MATCH 'packaged'\").fetchone()[0]==1; "
            "db.close(); print('socket/TLS/SQLite FTS5/ctypes/Rust/MCP imports passed')",
        )
        db = root / "knowledge.db"
        wiki = root / "wiki"

        def token(revision, content):
            return {
                "source_id": "meeting:binary-smoke",
                "revision": revision,
                "source_version": str(revision),
                "content_hash": content,
                "extractor_version": "1",
                "ontology_version": "1",
            }

        def apply(request, expected=0):
            return run("lifecycle", "apply", "-", "--db-path", db,
                       request=request, expected=expected)

        def observe(revision, content):
            apply({**token(revision, content), "action": "observe",
                   "location": "app://meeting/binary-smoke", "kind": "meeting",
                   "scope_id": None, "source_channel": "meeting"})

        def replacement(revision, content, value, job):
            return {
                **token(revision, content), "action": "replace", "job_id": job,
                "complete": True, "checkpoint": {"cursor": revision},
                "entities": [{"id": "project:binary-smoke", "type": "project",
                              "name": "Binary Smoke", "properties": {"status": value}}],
                "relations": [],
            }

        observe(1, "A")
        apply(replacement(1, "A", "planned", "job-1"))
        observe(2, "B")
        apply(replacement(2, "B", "active", "job-2"))
        observe(3, "A")
        apply(replacement(2, "B", "stale", "late-job-2"), expected=1)
        apply(replacement(3, "A", "planned", "job-3"))
        run("lifecycle", "rebuild", "--db-path", db, "--wiki-root", wiki)
        # A second publication also exercises replacement of an existing index.
        run("lifecycle", "rebuild", "--db-path", db, "--wiki-root", wiki)
        state = json.loads(run("lifecycle", "status", "--db-path", db))
        assert state["wiki_dirty"] is False, state
        text = (wiki / "index.md").read_text(encoding="utf-8")
        assert '"status": "planned"' in text and '"status": "stale"' not in text, text
        print(json.dumps({"version": actual_version, "native_runtime": "passed",
                          "lifecycle": "A->B->A, stale rejection, wiki replacement passed",
                          "state": state}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    smoke(arguments.binary.resolve(), arguments.version)
