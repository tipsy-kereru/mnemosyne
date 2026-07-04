"""
Schema engine for managing schema packs.

Provides loading, type inference, and schema evolution.
"""

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

logger = logging.getLogger(__name__)


@dataclass
class EntityType:
    """Entity type definition."""

    name: str
    description: str = ""
    primitive: str = "entity"  # entity | temporal | annotation
    prefix_patterns: List[str] = field(default_factory=list)
    extractable: bool = False
    expert_routing: bool = False
    properties: Dict[str, str] = field(default_factory=dict)


@dataclass
class LinkType:
    """Relationship type definition."""

    name: str
    description: str = ""
    from_type: str = ""
    to_type: str = ""
    inferred: bool = False


@dataclass
class SearchDefaults:
    """Search mode defaults for the schema."""

    use_graph: bool = True
    use_reranker: bool = False
    max_results: int = 20


@dataclass
class SchemaPack:
    """Complete schema pack."""

    name: str
    version: str = "1.0"
    api_version: str = "1.0"
    inherits: Optional[str] = None
    types: Dict[str, EntityType] = field(default_factory=dict)
    link_types: Dict[str, LinkType] = field(default_factory=dict)
    search_defaults: Dict[str, Any] = field(default_factory=dict)

    def get_type(self, type_name: str) -> Optional[EntityType]:
        """Get entity type by name."""
        return self.types.get(type_name)

    def get_link_type(self, link_name: str) -> Optional[LinkType]:
        """Get link type by name."""
        return self.link_types.get(link_name)


class SchemaEngine:
    """Schema management and resolution."""

    def __init__(self, packs_dir: Optional[Path] = None):
        """Initialize schema engine.

        Args:
            packs_dir: Directory containing schema packs.
                Defaults to ~/.mnemosyne/schema-packs/
        """
        if packs_dir is None:
            packs_dir = Path.home() / ".mnemosyne" / "schema-packs"

        self.packs_dir = Path(packs_dir)
        self.active_pack: Optional[SchemaPack] = None
        self._pack_cache: Dict[str, SchemaPack] = {}

        # Ensure directories exist
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create pack directories if they don't exist."""
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        (self.packs_dir / "builtin").mkdir(exist_ok=True)
        (self.packs_dir / "custom").mkdir(exist_ok=True)

    def load_pack(self, pack_name: str) -> Optional[SchemaPack]:
        """Load a schema pack from disk.

        Args:
            pack_name: Name of the pack (e.g., "base-v1", "custom/my-pack")

        Returns:
            SchemaPack or None if not found.
        """
        # Check cache first
        if pack_name in self._pack_cache:
            return self._pack_cache[pack_name]

        # Find the pack file
        pack_path = self._find_pack_path(pack_name)
        if not pack_path or not pack_path.exists():
            logger.warning(f"Schema pack not found: {pack_name}")
            return None

        try:
            with open(pack_path, "r") as f:
                data = yaml.safe_load(f)

            pack = self._parse_pack(data)

            # Handle inheritance
            if pack.inherits:
                parent = self.load_pack(pack.inherits)
                if parent:
                    pack = self._merge_packs(parent, pack)

            self._pack_cache[pack_name] = pack
            return pack

        except Exception as e:
            logger.error(f"Failed to load pack {pack_name}: {e}")
            return None

    def _find_pack_path(self, pack_name: str) -> Optional[Path]:
        """Find the pack.yaml file for a given pack name."""
        # Try custom first
        custom_path = self.packs_dir / "custom" / pack_name / "pack.yaml"
        if custom_path.exists():
            return custom_path

        # Try builtin
        builtin_path = self.packs_dir / "builtin" / pack_name / "pack.yaml"
        if builtin_path.exists():
            return builtin_path

        # Try direct name
        direct_path = self.packs_dir / pack_name / "pack.yaml"
        if direct_path.exists():
            return direct_path

        return None

    def _parse_pack(self, data: Dict) -> SchemaPack:
        """Parse pack data into SchemaPack."""
        # Parse entity types
        types = {}
        for name, type_data in data.get("types", {}).items():
            types[name] = EntityType(
                name=name,
                description=type_data.get("description", ""),
                primitive=type_data.get("primitive", "entity"),
                prefix_patterns=type_data.get("prefix_patterns", []),
                extractable=type_data.get("extractable", False),
                expert_routing=type_data.get("expert_routing", False),
                properties=type_data.get("properties", {}),
            )

        # Parse link types
        link_types = {}
        for name, link_data in data.get("link_types", {}).items():
            link_types[name] = LinkType(
                name=name,
                description=link_data.get("description", ""),
                from_type=link_data.get("from", ""),
                to_type=link_data.get("to", ""),
                inferred=link_data.get("inferred", False),
            )

        return SchemaPack(
            name=data.get("name", ""),
            version=data.get("version", "1.0"),
            api_version=data.get("api_version", "1.0"),
            inherits=data.get("inherits"),
            types=types,
            link_types=link_types,
            search_defaults=data.get("search_defaults", {}),
        )

    def _merge_packs(self, parent: SchemaPack, child: SchemaPack) -> SchemaPack:
        """Merge child pack with parent inheritance."""
        merged = SchemaPack(
            name=child.name,
            version=child.version,
            api_version=child.api_version,
            inherits=child.inherits,
            types=parent.types.copy(),
            link_types=parent.link_types.copy(),
            search_defaults=parent.search_defaults.copy(),
        )

        # Child overrides parent
        merged.types.update(child.types)
        merged.link_types.update(child.link_types)
        merged.search_defaults.update(child.search_defaults)

        return merged

    def set_active(self, pack_name: str) -> bool:
        """Set the active schema pack.

        Args:
            pack_name: Name of the pack to activate.

        Returns:
            True if successful, False otherwise.
        """
        pack = self.load_pack(pack_name)
        if not pack:
            return False

        self.active_pack = pack

        # Update ACTIVE symlink
        active_link = self.packs_dir / "ACTIVE"
        pack_path = self._find_pack_path(pack_name)

        if active_link.exists():
            active_link.unlink()

        if pack_path and pack_path.parent:
            try:
                active_link.symlink_to(pack_path.parent)
            except OSError:
                logger.warning(f"Could not create ACTIVE symlink")

        logger.info(f"Activated schema pack: {pack_name}")
        return True

    def infer_type(self, file_path: str) -> Optional[str]:
        """Infer entity type from file path using active pack.

        Args:
            file_path: Path to entity file.

        Returns:
            Type name or None.
        """
        if not self.active_pack:
            return None

        for type_name, type_def in self.active_pack.types.items():
            for pattern in type_def.prefix_patterns:
                if self._match_pattern(file_path, pattern):
                    return type_name

        return None

    def _match_pattern(self, path: str, pattern: str) -> bool:
        """Match path against glob pattern."""
        # Convert pattern to glob and check
        # Handle patterns like "people/**" or "contacts/*.md"
        glob_pattern = pattern.replace("**", "*")
        return fnmatch.fnmatch(path, glob_pattern) or fnmatch.fnmatch(
            path, f"*{glob_pattern}"
        )

    def is_extractable(self, type_name: str) -> bool:
        """Check if type should have fact extraction.

        Args:
            type_name: Entity type name.

        Returns:
            True if extractable, False otherwise.
        """
        if not self.active_pack:
            return False

        type_def = self.active_pack.get_type(type_name)
        return type_def.extractable if type_def else False

    def is_expert_routing(self, type_name: str) -> bool:
        """Check if type should route through expert search.

        Args:
            type_name: Entity type name.

        Returns:
            True if expert routing, False otherwise.
        """
        if not self.active_pack:
            return False

        type_def = self.active_pack.get_type(type_name)
        return type_def.expert_routing if type_def else False

    def list_packs(self) -> List[str]:
        """List all available schema packs.

        Returns:
            List of pack names.
        """
        packs = set()

        # Scan builtin
        builtin_dir = self.packs_dir / "builtin"
        if builtin_dir.exists():
            for item in builtin_dir.iterdir():
                if item.is_dir() and (item / "pack.yaml").exists():
                    packs.add(item.name)

        # Scan custom
        custom_dir = self.packs_dir / "custom"
        if custom_dir.exists():
            for item in custom_dir.iterdir():
                if item.is_dir() and (item / "pack.yaml").exists():
                    packs.add(item.name)

        return sorted(packs)

    def get_active_pack_name(self) -> Optional[str]:
        """Get the name of the active pack.

        Returns:
            Pack name or None.
        """
        if not self.active_pack:
            return None

        # Try to read from symlink
        active_link = self.packs_dir / "ACTIVE"
        if active_link.exists() and active_link.is_symlink():
            target = active_link.resolve()
            return target.name

        return self.active_pack.name


def load_builtin_pack(pack_name: str) -> Optional[SchemaPack]:
    """Load a builtin schema pack.

    Convenience function for loading default packs.

    Args:
        pack_name: Name of the builtin pack (e.g., "base-v1").

    Returns:
        SchemaPack or None.
    """
    from importlib.resources import files

    try:
        pack_path = files(__package__) / "packs" / pack_name / "pack.yaml"
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)

        engine = SchemaEngine()
        return engine._parse_pack(data)

    except Exception:
        return None
