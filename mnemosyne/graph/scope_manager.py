"""
Scope Manager for Hierarchical Session Memory

Manages project-topic-session hierarchy with SQLite recursive CTEs
for efficient tree traversal.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional


from mnemosyne.graph.knowledge_graph import Scope

# Valid scope types and their parent constraints
_SCOPE_TYPE_PARENT_RULES = {
    'project': lambda parent_id: parent_id is None,
    'topic': lambda parent_id: parent_id is not None,
    'session': lambda parent_id: parent_id is not None,
}


class ScopeManager:
    """
    Manages hierarchical scope entities for session-scoped memory.

    Hierarchy: project -> topic -> session (infinite depth supported
    for sessions nesting under sessions).
    """

    def __init__(self, conn: sqlite3.Connection):
        # @MX:ANCHOR: [AUTO] ScopeManager is the central scope CRUD handler
        # @MX:REASON: Used by KnowledgeGraph, query engine, and CLI for all scope operations
        self.conn = conn

    def create_scope(
        self,
        scope_type: str,
        name: str,
        parent_id: Optional[str] = None,
        source_channel: str = 'unknown',
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Scope:
        """
        Create a new scope in the hierarchy.

        Args:
            scope_type: One of 'project', 'topic', 'session'
            name: Human-readable name for the scope
            parent_id: Parent scope ID (NULL for projects)
            source_channel: Origin channel (discord, teams, slack, code, manual)
            metadata: Optional metadata dict

        Returns:
            Created Scope instance

        Raises:
            ValueError: If scope_type is invalid or parent constraint violated
        """
        if scope_type not in _SCOPE_TYPE_PARENT_RULES:
            raise ValueError(
                f"Invalid scope_type '{scope_type}'. "
                f"Must be one of: {list(_SCOPE_TYPE_PARENT_RULES.keys())}"
            )

        validation_fn = _SCOPE_TYPE_PARENT_RULES[scope_type]
        if not validation_fn(parent_id):
            if scope_type == 'project':
                raise ValueError("Project scopes must have parent_id = None")
            else:
                raise ValueError(
                    f"{scope_type.capitalize()} scopes require a parent_id"
                )

        # Validate parent exists and has an allowed type
        if parent_id is not None:
            parent = self.get_scope(parent_id)
            if parent is None:
                raise ValueError(f"Parent scope '{parent_id}' not found")
            if scope_type == 'topic' and parent.scope_type != 'project':
                raise ValueError(
                    f"Topic scopes must have a project as parent, "
                    f"got '{parent.scope_type}'"
                )
            if scope_type == 'session' and parent.scope_type not in ('topic', 'session'):
                raise ValueError(
                    f"Session scopes must have a topic or session as parent, "
                    f"got '{parent.scope_type}'"
                )

        now = datetime.utcnow().isoformat()
        scope_id = uuid.uuid4().hex
        scope_metadata = metadata or {}

        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO scopes (id, parent_id, scope_type, name, metadata, source_channel, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            scope_id,
            parent_id,
            scope_type,
            name,
            json.dumps(scope_metadata),
            source_channel,
            now,
        ))
        self.conn.commit()

        return Scope(
            id=scope_id,
            parent_id=parent_id,
            scope_type=scope_type,
            name=name,
            created_at=now,
            metadata=scope_metadata,
            source_channel=source_channel,
        )

    def get_scope(self, scope_id: str) -> Optional[Scope]:
        """Retrieve a scope by its ID."""
        cursor = self.conn.cursor()
        row = cursor.execute(
            'SELECT * FROM scopes WHERE id = ?', (scope_id,)
        ).fetchone()

        if row is None:
            return None

        return self._row_to_scope(row)

    def get_ancestors(self, scope_id: str) -> List[Scope]:
        """
        Get all ancestor scopes from immediate parent up to root.
        Uses recursive CTE for efficient traversal.
        """
        cursor = self.conn.cursor()
        rows = cursor.execute('''
            WITH RECURSIVE ancestors(id, parent_id, scope_type, name, metadata, source_channel, created_at) AS (
                SELECT s.id, s.parent_id, s.scope_type, s.name, s.metadata, s.source_channel, s.created_at
                FROM scopes s
                WHERE s.id = (SELECT parent_id FROM scopes WHERE id = ?)
                UNION ALL
                SELECT s.id, s.parent_id, s.scope_type, s.name, s.metadata, s.source_channel, s.created_at
                FROM scopes s
                JOIN ancestors a ON s.id = a.parent_id
            )
            SELECT * FROM ancestors
        ''', (scope_id,)).fetchall()

        return [self._row_to_scope(row) for row in rows]

    def get_children(self, scope_id: str) -> List[Scope]:
        """Get direct children of a scope."""
        cursor = self.conn.cursor()
        rows = cursor.execute(
            'SELECT * FROM scopes WHERE parent_id = ?', (scope_id,)
        ).fetchall()

        return [self._row_to_scope(row) for row in rows]

    def get_siblings(self, scope_id: str) -> List[Scope]:
        """Get scopes sharing the same parent, excluding self."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return []

        cursor = self.conn.cursor()
        if scope.parent_id is None:
            # Root-level siblings: other scopes with no parent
            rows = cursor.execute(
                'SELECT * FROM scopes WHERE parent_id IS NULL AND id != ?',
                (scope_id,),
            ).fetchall()
        else:
            rows = cursor.execute(
                'SELECT * FROM scopes WHERE parent_id = ? AND id != ?',
                (scope.parent_id, scope_id),
            ).fetchall()

        return [self._row_to_scope(row) for row in rows]

    def get_descendants(self, scope_id: str) -> List[Scope]:
        """
        Get all descendant scopes (children, grandchildren, etc.).
        Uses recursive CTE for efficient traversal.
        """
        cursor = self.conn.cursor()
        rows = cursor.execute('''
            WITH RECURSIVE descendants(id, parent_id, scope_type, name, metadata, source_channel, created_at) AS (
                SELECT s.id, s.parent_id, s.scope_type, s.name, s.metadata, s.source_channel, s.created_at
                FROM scopes s
                WHERE s.parent_id = ?
                UNION ALL
                SELECT s.id, s.parent_id, s.scope_type, s.name, s.metadata, s.source_channel, s.created_at
                FROM scopes s
                JOIN descendants d ON s.parent_id = d.id
            )
            SELECT * FROM descendants
        ''', (scope_id,)).fetchall()

        return [self._row_to_scope(row) for row in rows]

    def find_scope_by_name(
        self, name: str, scope_type: Optional[str] = None
    ) -> Optional[Scope]:
        """Find a scope by name, optionally filtered by type."""
        cursor = self.conn.cursor()

        if scope_type:
            row = cursor.execute(
                'SELECT * FROM scopes WHERE name = ? AND scope_type = ?',
                (name, scope_type),
            ).fetchone()
        else:
            row = cursor.execute(
                'SELECT * FROM scopes WHERE name = ?', (name,)
            ).fetchone()

        if row is None:
            return None

        return self._row_to_scope(row)

    def delete_scope(self, scope_id: str, cascade: bool = False) -> bool:
        """
        Delete a scope.

        Args:
            scope_id: ID of the scope to delete
            cascade: If True, also delete all descendant scopes and
                     reassign their entities to global scope (scope_id=NULL).
                     If False, refuse to delete if children exist.

        Returns:
            True if deleted, False if scope not found

        Raises:
            ValueError: If scope has children and cascade is False
        """
        scope = self.get_scope(scope_id)
        if scope is None:
            return False

        children = self.get_children(scope_id)
        if children and not cascade:
            raise ValueError(
                f"Scope '{scope.name}' has {len(children)} children. "
                f"Use cascade=True to delete with descendants."
            )

        cursor = self.conn.cursor()

        if cascade:
            # Collect all descendant IDs
            descendant_ids = [scope_id]
            for d in self.get_descendants(scope_id):
                descendant_ids.append(d.id)

            # Reassign entities in deleted scopes to global (NULL)
            placeholders = ','.join('?' * len(descendant_ids))
            cursor.execute(
                f'UPDATE entities SET scope_id = NULL WHERE scope_id IN ({placeholders})',
                descendant_ids,
            )
            cursor.execute(
                f'UPDATE relations SET scope_id = NULL WHERE scope_id IN ({placeholders})',
                descendant_ids,
            )
            # Delete all descendant scopes (including self)
            cursor.execute(
                f'DELETE FROM scopes WHERE id IN ({placeholders})',
                descendant_ids,
            )
        else:
            # No children, safe to delete directly
            cursor.execute(
                'UPDATE entities SET scope_id = NULL WHERE scope_id = ?',
                (scope_id,),
            )
            cursor.execute(
                'UPDATE relations SET scope_id = NULL WHERE scope_id = ?',
                (scope_id,),
            )
            cursor.execute(
                'DELETE FROM scopes WHERE id = ?', (scope_id,)
            )

        self.conn.commit()
        return True

    def resolve_visible_scope_ids(self, scope_id: str) -> List[Optional[str]]:
        """
        Return scope IDs visible from the given scope.

        The result includes: [self_id, ...descendant_ids, ...ancestor_ids, None]
        where None represents the global scope. Entities in any of these scopes
        are visible from the given scope.

        Visibility model:
        - An entity is visible from its own scope
        - An entity in a descendant scope is visible (you can see "down")
        - An entity in an ancestor scope is visible (it "flows down" to you)
        - Global scope (NULL) entities are always visible

        Args:
            scope_id: The scope to resolve visibility for

        Returns:
            List of scope IDs (including None for global).
        """
        result: List[Optional[str]] = [scope_id]

        # Include descendants (entities "below" this scope are visible)
        descendants = self.get_descendants(scope_id)
        for d in descendants:
            result.append(d.id)

        # Include ancestors (entities "above" flow down to this scope)
        ancestors = self.get_ancestors(scope_id)
        for ancestor in ancestors:
            result.append(ancestor.id)

        # Global scope (NULL) is always visible
        result.append(None)
        return result

    def _row_to_scope(self, row: sqlite3.Row) -> Scope:
        """Convert a database row to a Scope dataclass."""
        return Scope(
            id=row['id'],
            parent_id=row['parent_id'],
            scope_type=row['scope_type'],
            name=row['name'],
            created_at=row['created_at'],
            metadata=json.loads(row['metadata'] or '{}'),
            source_channel=row['source_channel'],
        )
