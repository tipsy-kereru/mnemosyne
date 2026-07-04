"""
Tests for schema pack system.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from mnemosyne.schema.engine import (
    SchemaEngine,
    SchemaPack,
    EntityType,
    LinkType,
)


@pytest.fixture
def temp_packs_dir():
    """Create temporary packs directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        packs_dir = Path(tmpdir) / "schema-packs"
        packs_dir.mkdir()
        (packs_dir / "builtin").mkdir()
        (packs_dir / "custom").mkdir()

        # Create test pack
        test_pack_dir = packs_dir / "builtin" / "test-v1"
        test_pack_dir.mkdir()

        test_pack_data = {
            "api_version": "1.0",
            "name": "test",
            "version": "1.0",
            "types": {
                "person": {
                    "description": "A person",
                    "primitive": "entity",
                    "prefix_patterns": ["people/**"],
                    "extractable": True,
                    "expert_routing": True,
                    "properties": {"name": "string", "email": "string"},
                }
            },
            "link_types": {
                "knows": {
                    "description": "Person knows person",
                    "from": "person",
                    "to": "person",
                    "inferred": True,
                }
            },
            "search_defaults": {"use_graph": True, "max_results": 20},
        }

        with open(test_pack_dir / "pack.yaml", "w") as f:
            yaml.dump(test_pack_data, f)

        yield packs_dir


class TestSchemaEngine:
    """Tests for SchemaEngine."""

    def test_initialization(self, temp_packs_dir):
        """Engine should initialize with packs directory."""
        engine = SchemaEngine(temp_packs_dir)

        assert engine.packs_dir == temp_packs_dir
        assert (temp_packs_dir / "builtin").exists()
        assert (temp_packs_dir / "custom").exists()

    def test_load_pack(self, temp_packs_dir):
        """Should load pack from disk."""
        engine = SchemaEngine(temp_packs_dir)

        pack = engine.load_pack("test-v1")

        assert pack is not None
        assert pack.name == "test"
        assert pack.version == "1.0"

    def test_pack_types(self, temp_packs_dir):
        """Pack should have entity types."""
        engine = SchemaEngine(temp_packs_dir)

        pack = engine.load_pack("test-v1")

        assert "person" in pack.types

        person_type = pack.types["person"]
        assert person_type.name == "person"
        assert person_type.primitive == "entity"
        assert person_type.extractable is True
        assert person_type.expert_routing is True

    def test_pack_link_types(self, temp_packs_dir):
        """Pack should have link types."""
        engine = SchemaEngine(temp_packs_dir)

        pack = engine.load_pack("test-v1")

        assert "knows" in pack.link_types

        knows_link = pack.link_types["knows"]
        assert knows_link.name == "knows"
        assert knows_link.from_type == "person"
        assert knows_link.to_type == "person"
        assert knows_link.inferred is True

    def test_pack_search_defaults(self, temp_packs_dir):
        """Pack should have search defaults."""
        engine = SchemaEngine(temp_packs_dir)

        pack = engine.load_pack("test-v1")

        assert pack.search_defaults["use_graph"] is True
        assert pack.search_defaults["max_results"] == 20

    def test_set_active(self, temp_packs_dir):
        """Should set active pack."""
        engine = SchemaEngine(temp_packs_dir)

        result = engine.set_active("test-v1")

        assert result is True
        assert engine.active_pack is not None
        assert engine.active_pack.name == "test"

    def test_infer_type(self, temp_packs_dir):
        """Should infer type from path."""
        engine = SchemaEngine(temp_packs_dir)
        engine.set_active("test-v1")

        # Match pattern
        assert engine.infer_type("people/john-doe") == "person"
        assert engine.infer_type("people/subdir/jane") == "person"

        # No match
        assert engine.infer_type("organizations/acme") is None

    def test_is_extractable(self, temp_packs_dir):
        """Should check if type is extractable."""
        engine = SchemaEngine(temp_packs_dir)
        engine.set_active("test-v1")

        assert engine.is_extractable("person") is True

    def test_is_extractable_no_active_pack(self, temp_packs_dir):
        """Should return False when no active pack."""
        engine = SchemaEngine(temp_packs_dir)

        assert engine.is_extractable("person") is False

    def test_is_expert_routing(self, temp_packs_dir):
        """Should check if type uses expert routing."""
        engine = SchemaEngine(temp_packs_dir)
        engine.set_active("test-v1")

        assert engine.is_expert_routing("person") is True

    def test_is_expert_routing_no_active_pack(self, temp_packs_dir):
        """Should return False when no active pack."""
        engine = SchemaEngine(temp_packs_dir)

        assert engine.is_expert_routing("person") is False

    def test_list_packs(self, temp_packs_dir):
        """Should list available packs."""
        engine = SchemaEngine(temp_packs_dir)

        packs = engine.list_packs()

        assert "test-v1" in packs

    def test_get_active_pack_name(self, temp_packs_dir):
        """Should return active pack name."""
        engine = SchemaEngine(temp_packs_dir)
        engine.set_active("test-v1")

        assert engine.get_active_pack_name() == "test-v1"

    def test_load_nonexistent_pack(self, temp_packs_dir):
        """Should return None for nonexistent pack."""
        engine = SchemaEngine(temp_packs_dir)

        pack = engine.load_pack("nonexistent")

        assert pack is None

    def test_pack_caching(self, temp_packs_dir):
        """Should cache loaded packs."""
        engine = SchemaEngine(temp_packs_dir)

        pack1 = engine.load_pack("test-v1")
        pack2 = engine.load_pack("test-v1")

        # Should be same object (cached)
        assert pack1 is pack2


class TestPackInheritance:
    """Tests for pack inheritance."""

    @pytest.fixture
    def inheritance_packs_dir(self):
        """Create packs with inheritance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            packs_dir = Path(tmpdir) / "schema-packs"
            packs_dir.mkdir()
            (packs_dir / "builtin").mkdir()

            # Parent pack
            parent_dir = packs_dir / "builtin" / "parent-v1"
            parent_dir.mkdir()

            parent_data = {
                "api_version": "1.0",
                "name": "parent",
                "version": "1.0",
                "types": {
                    "base_type": {
                        "description": "Base type",
                        "primitive": "entity",
                        "extractable": False,
                    }
                },
                "link_types": {
                    "base_link": {
                        "description": "Base link",
                        "from": "base_type",
                        "to": "base_type",
                    }
                },
            }

            with open(parent_dir / "pack.yaml", "w") as f:
                yaml.dump(parent_data, f)

            # Child pack
            child_dir = packs_dir / "builtin" / "child-v1"
            child_dir.mkdir()

            child_data = {
                "api_version": "1.0",
                "name": "child",
                "version": "1.0",
                "inherits": "parent-v1",
                "types": {
                    "child_type": {
                        "description": "Child type",
                        "primitive": "entity",
                        "extractable": True,
                    }
                },
            }

            with open(child_dir / "pack.yaml", "w") as f:
                yaml.dump(child_data, f)

            yield packs_dir

    def test_inheritance_loads_parent_types(self, inheritance_packs_dir):
        """Child pack should include parent types."""
        engine = SchemaEngine(inheritance_packs_dir)

        pack = engine.load_pack("child-v1")

        assert "base_type" in pack.types
        assert "child_type" in pack.types

    def test_inheritance_loads_parent_links(self, inheritance_packs_dir):
        """Child pack should include parent link types."""
        engine = SchemaEngine(inheritance_packs_dir)

        pack = engine.load_pack("child-v1")

        assert "base_link" in pack.link_types


class TestPatternMatching:
    """Tests for pattern matching."""

    def test_match_pattern_exact(self):
        """Should match exact patterns."""
        engine = SchemaEngine()

        assert engine._match_pattern("people/john", "people/**")

    def test_match_pattern_subdirectory(self):
        """Should match subdirectory patterns."""
        engine = SchemaEngine()

        assert engine._match_pattern("people/subdir/john", "people/**")

    def test_match_pattern_no_match(self):
        """Should not match non-matching paths."""
        engine = SchemaEngine()

        assert not engine._match_pattern("organizations/acme", "people/**")

    def test_match_pattern_wildcard(self):
        """Should match wildcard patterns."""
        engine = SchemaEngine()

        assert engine._match_pattern("test.md", "*.md")


class TestSchemaPack:
    """Tests for SchemaPack dataclass."""

    def test_get_type(self):
        """Should retrieve type by name."""
        pack = SchemaPack(
            name="test",
            types={"person": EntityType(name="person")},
        )

        assert pack.get_type("person") is not None
        assert pack.get_type("nonexistent") is None

    def test_get_link_type(self):
        """Should retrieve link type by name."""
        pack = SchemaPack(
            name="test",
            link_types={"knows": LinkType(name="knows")},
        )

        assert pack.get_link_type("knows") is not None
        assert pack.get_link_type("nonexistent") is None
