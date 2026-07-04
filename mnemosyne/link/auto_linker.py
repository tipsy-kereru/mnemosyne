"""
Auto-linker for automatic relationship creation.

Processes entity writes and creates relationships automatically.
"""

import logging
from typing import Dict, List, Optional, Tuple

from mnemosyne.link.extractor import LinkExtractor
from mnemosyne.schema.engine import SchemaEngine

logger = logging.getLogger(__name__)


class AutoLinker:
    """Automatically create links on entity writes."""

    def __init__(self, knowledge_graph, schema: Optional[SchemaEngine] = None):
        """Initialize auto-linker.

        Args:
            knowledge_graph: KnowledgeGraph instance for creating relations.
            schema: Optional SchemaEngine for type inference.
        """
        self.kg = knowledge_graph
        self.schema = schema
        self.extractor = LinkExtractor()

    def on_entity_write(self, entity_id: str, content: str, entity_type: Optional[str] = None) -> int:
        """Process entity write and create auto-links.

        Args:
            entity_id: ID of the entity being written.
            content: Markdown content of the entity.
            entity_type: Type of the entity (optional).

        Returns:
            Number of links created.
        """
        if not content:
            return 0

        # Extract links with inferred types
        links = self.extractor.extract_and_infer(content, entity_type)

        if not links:
            return 0

        links_created = 0

        for link_text, target_path, inferred_type in links:
            # Resolve target entity
            target_id = self._resolve_target(target_path)

            if not target_id:
                # Create stub entity
                target_id = self._create_stub(target_path)

            if not target_id:
                continue

            # Create relationship
            if self._create_relation(entity_id, target_id, inferred_type, link_text):
                links_created += 1

        logger.debug(f"Auto-linked {links_created} relationships for {entity_id}")
        return links_created

    def _resolve_target(self, target_path: str) -> Optional[str]:
        """Resolve target path to entity ID.

        Args:
            target_path: Path or identifier of target entity.

        Returns:
            Entity ID or None if not found.
        """
        # Try direct lookup by ID
        entity = self.kg.get_entity(target_path)
        if entity:
            return entity.id

        # Try lookup by name
        entities = self.kg.query(f"name:{target_path}", limit=5)
        if entities:
            return entities[0].id

        return None

    def _create_stub(self, target_path: str) -> Optional[str]:
        """Create stub entity for unknown target.

        Args:
            target_path: Path of the unknown target.

        Returns:
            New entity ID or None if creation failed.
        """
        # Infer type from path if schema available
        inferred_type = None
        if self.schema:
            inferred_type = self.schema.infer_type(target_path)

        # Generate entity ID from path
        entity_id = target_path.replace("/", "_").replace(" ", "-").lower()

        # Create stub entity
        try:
            self.kg.add_entity(
                entity_id=entity_id,
                entity_type=inferred_type or "entity",
                name=target_path,
                properties={"_stub": True, "_created_by": "autolink"},
            )
            logger.debug(f"Created stub entity: {entity_id}")
            return entity_id
        except Exception as e:
            logger.warning(f"Failed to create stub entity {target_path}: {e}")
            return None

    def _create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: Optional[str],
        link_text: str,
    ) -> bool:
        """Create relationship between entities.

        Args:
            source_id: Source entity ID.
            target_id: Target entity ID.
            relation_type: Type of relationship.
            link_text: Text of the link (for properties).

        Returns:
            True if relation created, False otherwise.
        """
        # Default to 'mentions' if no type inferred
        if not relation_type:
            relation_type = "mentions"

        # Check if relation already exists
        existing = self.kg.get_relation(source_id, target_id, relation_type)
        if existing:
            return False

        try:
            self.kg.add_relation(
                relation_id=f"{source_id}_{relation_type}_{target_id}",
                from_entity=source_id,
                to_entity=target_id,
                relation_type=relation_type,
                properties={"link_text": link_text, "inferred": True},
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to create relation: {e}")
            return False

    def batch_process(
        self,
        entities: List[Tuple[str, str, Optional[str]]],
    ) -> int:
        """Process multiple entities for auto-linking.

        Args:
            entities: List of (entity_id, content, entity_type) tuples.

        Returns:
            Total number of links created.
        """
        total_links = 0

        for entity_id, content, entity_type in entities:
            links = self.on_entity_write(entity_id, content, entity_type)
            total_links += links

        return total_links

    def unlink_entity(self, entity_id: str) -> int:
        """Remove all auto-created links for an entity.

        Args:
            entity_id: Entity to unlink.

        Returns:
            Number of links removed.
        """
        # Get all inferred relations
        relations = self.kg.get_entity_relations(entity_id)

        removed = 0
        for relation in relations:
            if relation.properties.get("inferred"):
                try:
                    self.kg.delete_relation(relation.id)
                    removed += 1
                except Exception as e:
                    logger.warning(f"Failed to delete relation {relation.id}: {e}")

        logger.debug(f"Removed {removed} auto-links for {entity_id}")
        return removed
