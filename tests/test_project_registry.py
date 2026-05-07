"""Tests for project-scoped knowledge graph — SPEC-PROJECT-REGISTRY-001."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph
from mnemosyne.graph.project import detect_project, resolve_scope_id


@pytest.fixture
def kg(tmp_path: Path) -> KnowledgeGraph:
    db = tmp_path / "test.db"
    return KnowledgeGraph(db_path=str(db))


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    p = tmp_path / "my-project"
    p.mkdir()
    (p / ".git").mkdir()
    (p / "src").mkdir()
    (p / "src" / "main.py").write_text("print('hello')")
    return p


class TestDetectProject:
    def test_detects_git_root(self, project_dir: Path) -> None:
        result = detect_project(start=project_dir)
        assert result is not None
        path, phash = result
        assert path == project_dir
        expected = hashlib.sha256(str(project_dir).encode()).hexdigest()
        assert phash == expected

    def test_detects_from_subdirectory(self, project_dir: Path) -> None:
        result = detect_project(start=project_dir / "src")
        assert result is not None
        assert result[0] == project_dir

    def test_detects_pyproject_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "pyproject"
        p.mkdir()
        (p / "pyproject.toml").write_text("[project]\nname='x'\n")
        result = detect_project(start=p)
        assert result is not None
        assert result[0] == p

    def test_returns_none_when_no_markers(self, tmp_path: Path) -> None:
        p = tmp_path / "empty"
        p.mkdir()
        # Walk-up detection may find markers above tmp_path (e.g. /tmp/.git),
        # so we patch the root check to prevent walking above our tmp boundary.
        with patch("mnemosyne.graph.project._PROJECT_MARKERS", (".nonexistent-marker-xyz",)):
            assert detect_project(start=p) is None


class TestProjectRegistration:
    def test_register_and_list(self, kg: KnowledgeGraph, tmp_path: Path) -> None:
        project_path = str(tmp_path / "proj-a")
        phash = hashlib.sha256(project_path.encode()).hexdigest()
        scope_id = kg.register_project(phash, "proj-a", project_path)

        assert scope_id is not None

        projects = kg.list_projects()
        assert len(projects) == 1
        assert projects[0]["project_name"] == "proj-a"

    def test_idempotent_register(self, kg: KnowledgeGraph) -> None:
        phash = "abc123"
        sid1 = kg.register_project(phash, "test", "/tmp/test")
        sid2 = kg.register_project(phash, "test", "/tmp/test")
        assert sid1 == sid2

    def test_get_by_hash(self, kg: KnowledgeGraph) -> None:
        phash = "hash1"
        kg.register_project(phash, "proj", "/tmp/proj")
        result = kg.get_project_by_hash(phash)
        assert result is not None
        assert result["project_name"] == "proj"

    def test_get_by_name(self, kg: KnowledgeGraph) -> None:
        phash = "hash2"
        kg.register_project(phash, "myproj", "/tmp/myproj")
        result = kg.get_project_by_name("myproj")
        assert result is not None

    def test_unregister(self, kg: KnowledgeGraph) -> None:
        phash = "hash3"
        kg.register_project(phash, "to-remove", "/tmp/remove")
        assert kg.unregister_project(phash) is True
        assert kg.get_project_by_hash(phash) is None
        assert len(kg.list_projects()) == 0

    def test_unregister_preserves_entities(self, kg: KnowledgeGraph) -> None:
        phash = "hash4"
        scope_id = kg.register_project(phash, "preserve", "/tmp/preserve")
        from mnemosyne.graph.knowledge_graph import Entity
        kg.add_entity(
            Entity(id="e1", type="function", name="f", properties={}, created_at="", updated_at=""),
            scope_id=scope_id,
        )
        kg.unregister_project(phash)
        entity = kg.get_entity("e1")
        assert entity is not None


class TestResolveScopeId:
    def test_explicit_scope_wins(self, kg: KnowledgeGraph) -> None:
        result = resolve_scope_id(kg, explicit_scope_id="custom")
        assert result == "custom"

    def test_auto_registers_project(self, kg: KnowledgeGraph, project_dir: Path) -> None:
        with patch("mnemosyne.graph.project.Path.cwd", return_value=project_dir):
            scope_id = resolve_scope_id(kg, start=project_dir)
        assert scope_id is not None
        projects = kg.list_projects()
        assert len(projects) == 1
        assert projects[0]["project_name"] == "my-project"

    def test_no_project_returns_none(self, kg: KnowledgeGraph, tmp_path: Path) -> None:
        empty = tmp_path / "nowhere"
        empty.mkdir()
        with patch("mnemosyne.graph.project._PROJECT_MARKERS", (".nonexistent-marker-xyz",)):
            assert resolve_scope_id(kg, start=empty) is None


class TestMigration:
    def test_migrate_orphan_scopes(self, kg: KnowledgeGraph) -> None:
        scope = kg.create_scope(scope_type="project", name="legacy-proj")
        from mnemosyne.graph.knowledge_graph import Entity
        kg.add_entity(
            Entity(id="e1", type="function", name="f", properties={}, created_at="", updated_at=""),
            scope_id=scope.id,
        )

        cursor = kg.conn.cursor()
        cursor.execute(
            "SELECT DISTINCT scope_id FROM entities WHERE scope_id IS NOT NULL"
        )
        assert len(cursor.fetchall()) == 1

        cursor.execute("SELECT COUNT(*) FROM projects")
        assert cursor.fetchone()[0] == 0

        from mnemosyne.cli import _run_project_migrate
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            _run_project_migrate(kg)
        finally:
            sys.stdout = old_stdout

        cursor.execute("SELECT COUNT(*) FROM projects")
        assert cursor.fetchone()[0] == 1

        entity = kg.get_entity("e1")
        assert entity is not None


class TestProjectCLI:
    def test_list_empty(self, kg: KnowledgeGraph) -> None:
        assert len(kg.list_projects()) == 0

    def test_register_and_list(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mnemosyne.cli import main

        proj = tmp_path / "cli-proj"
        proj.mkdir()

        main(["project", "register", str(proj)])
        main(["project", "list"])
        out = capsys.readouterr().out
        assert "cli-proj" in out

    def test_show_by_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mnemosyne.cli import main

        proj = tmp_path / "show-proj"
        proj.mkdir()

        main(["project", "register", str(proj)])
        capsys.readouterr()  # clear register output
        main(["project", "show", "show-proj"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["name"] == "show-proj"

    def test_unregister(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mnemosyne.cli import main

        proj = tmp_path / "rm-proj"
        proj.mkdir()

        main(["project", "register", str(proj)])
        main(["project", "unregister", "rm-proj"])
        out = capsys.readouterr().out
        assert "Unregistered" in out

    def test_show_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        from mnemosyne.cli import main

        main(["project", "show", "nonexistent"])
        out = capsys.readouterr().out
        assert "not found" in out
