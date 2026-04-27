"""
Tests for mnemosyne package structure and imports (SPEC-PKG-001).
"""

import re
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:
    import tomli as tomllib  # Python < 3.11 backport

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestPackageImport:
    """Verify the mnemosyne package is importable."""

    def test_import_mnemosyne(self):
        """import mnemosyne succeeds."""
        import mnemosyne  # noqa: F401
        assert mnemosyne is not None

    def test_version_string(self):
        """mnemosyne.__version__ is a non-empty string."""
        import mnemosyne
        assert isinstance(mnemosyne.__version__, str)
        assert len(mnemosyne.__version__) > 0

    def test_version_format(self):
        """mnemosyne.__version__ matches X.Y.Z semver pattern."""
        import mnemosyne
        assert re.match(r'^\d+\.\d+\.\d+$', mnemosyne.__version__), \
            f"Version '{mnemosyne.__version__}' does not match X.Y.Z pattern"


class TestPublicAPIImports:
    """Verify public API classes are importable from mnemosyne."""

    def test_import_knowledge_graph(self):
        """from mnemosyne import KnowledgeGraph succeeds."""
        from mnemosyne import KnowledgeGraph
        assert KnowledgeGraph is not None

    def test_import_scope_manager(self):
        """from mnemosyne import ScopeManager succeeds."""
        from mnemosyne import ScopeManager
        assert ScopeManager is not None

    def test_import_entities(self):
        """from mnemosyne import Entity, Relation, Scope succeeds."""
        from mnemosyne import Entity, Relation, Scope
        assert Entity is not None
        assert Relation is not None
        assert Scope is not None


class TestSubmoduleImports:
    """Verify subpackage imports work."""

    def test_import_graph_submodule(self):
        """from mnemosyne.graph import KnowledgeGraph, ScopeManager succeeds."""
        from mnemosyne.graph import KnowledgeGraph, ScopeManager
        assert KnowledgeGraph is not None
        assert ScopeManager is not None

    def test_import_tree_sitter_extractor(self):
        """from mnemosyne.extraction.deterministic import TreeSitterExtractor succeeds."""
        from mnemosyne.extraction.deterministic import TreeSitterExtractor
        assert TreeSitterExtractor is not None

    def test_import_spacy_extractor(self):
        """from mnemosyne.extraction.deterministic import SpaCyExtractor succeeds."""
        from mnemosyne.extraction.deterministic import SpaCyExtractor
        assert SpaCyExtractor is not None

    def test_import_semantic_extractor(self):
        """from mnemosyne.extraction.semantic import SemanticExtractor succeeds.

        This must work even without torch/transformers installed (fallback mode).
        """
        from mnemosyne.extraction.semantic import SemanticExtractor
        assert SemanticExtractor is not None

    def test_import_gliner2_extractor(self):
        """from mnemosyne.extraction.semantic import GLiNER2Extractor succeeds."""
        from mnemosyne.extraction.semantic import GLiNER2Extractor
        assert GLiNER2Extractor is not None

    def test_import_rebel_extractor(self):
        """from mnemosyne.extraction.semantic import REBELExtractor succeeds."""
        from mnemosyne.extraction.semantic import REBELExtractor
        assert REBELExtractor is not None


class TestPyprojectToml:
    """Verify pyproject.toml exists and has required fields."""

    @pytest.fixture
    def pyproject(self):
        """Load pyproject.toml."""
        path = PROJECT_ROOT / "pyproject.toml"
        with open(path, "rb") as f:
            return tomllib.load(f)

    def test_pyproject_toml_parseable(self):
        """pyproject.toml exists and is parseable."""
        path = PROJECT_ROOT / "pyproject.toml"
        assert path.exists(), "pyproject.toml not found"
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)

    def test_pyproject_has_required_fields(self, pyproject):
        """pyproject.toml has name, version, description, requires-python."""
        project = pyproject["project"]
        assert "name" in project
        assert "version" in project
        assert "description" in project
        assert "requires-python" in project

    def test_pyproject_package_name(self, pyproject):
        """PyPI package name is mnemosyne-kg."""
        assert pyproject["project"]["name"] == "mnemosyne-kg"

    def test_pyproject_version(self, pyproject):
        """Package version is 0.1.0."""
        assert pyproject["project"]["version"] == "0.1.0"

    def test_pyproject_requires_python(self, pyproject):
        """Requires Python >=3.11."""
        assert pyproject["project"]["requires-python"] == ">=3.11"

    def test_pyproject_build_system(self, pyproject):
        """Build system uses setuptools + wheel."""
        build_requires = pyproject["build-system"]["requires"]
        build_backend = pyproject["build-system"]["build-backend"]
        assert any("setuptools" in r for r in build_requires)
        assert any("wheel" in r for r in build_requires)
        assert "setuptools" in build_backend


class TestVersionManagement:
    """Verify version consistency between __init__.py and pyproject.toml."""

    def test_version_matches_pyproject(self):
        """mnemosyne.__version__ matches the version in pyproject.toml."""
        import mnemosyne
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        pyproject_version = data["project"]["version"]
        assert mnemosyne.__version__ == pyproject_version, (
            f"mnemosyne.__version__ ({mnemosyne.__version__}) != "
            f"pyproject.toml version ({pyproject_version})"
        )

    def test_version_semver_format(self):
        """Version matches X.Y.Z pattern with digits only."""
        import mnemosyne
        assert re.match(r'^\d+\.\d+\.\d+$', mnemosyne.__version__), \
            f"Version '{mnemosyne.__version__}' is not valid semver"

    def test_version_has_all_field(self):
        """mnemosyne.__all__ includes __version__."""
        import mnemosyne
        assert "__version__" in mnemosyne.__all__
