"""
Knowledge Graph Database
SQLite + NetworkX for temporal knowledge graph storage and querying
"""

import json
import logging
import sqlite3
from pathlib import Path
from mnemosyne.timestamps import utc_now_iso
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class Scope:
    """Hierarchical scope entity for session memory"""
    id: str
    scope_type: str  # 'project', 'topic', or 'session'
    name: str
    created_at: str
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_channel: str = 'unknown'


@dataclass
class Entity:
    """Knowledge graph entity"""
    id: str
    type: str
    name: str
    properties: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int = 1
    scope_id: Optional[str] = None
    source_channel: str = 'legacy'


@dataclass
class Relation:
    """Knowledge graph relation"""
    id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any]
    created_at: str
    version: int = 1
    scope_id: Optional[str] = None
    source_channel: str = 'legacy'


class KnowledgeGraph:
    """
    Temporal knowledge graph with SQLite persistence and NetworkX analysis
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            _new_path = Path.home() / "mnemosyne" / "graph" / "knowledge.db"
            _legacy_path = Path.home() / "agent-memory" / "mnemosyne" / "graph" / "knowledge.db"
            if not _new_path.exists() and _legacy_path.exists():
                resolved = _legacy_path
            else:
                resolved = _new_path
        else:
            resolved = Path(db_path)

        self.db_path = resolved
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self._init_db()
        self.nx_graph = self._build_networkx()

        # Wire ScopeManager after DB is initialized
        from mnemosyne.graph.scope_manager import ScopeManager
        self.scope_manager = ScopeManager(self.conn)

    def _init_db(self):
        """Initialize database schema with session support"""
        cursor = self.conn.cursor()

        # Entities table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT,  -- JSON
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1
            )
        ''')

        # Relations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT,  -- JSON
                created_at TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            )
        ''')

        # Entity history for temporal tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT,
                changed_at TEXT NOT NULL,
                change_type TEXT NOT NULL,  -- created, updated, deleted
                version INTEGER
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(relation_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)')

        self.conn.commit()

        # Session schema migration (idempotent)
        self._init_session_schema()

    def _init_session_schema(self):
        """Add session-related tables and columns (idempotent migration)"""
        cursor = self.conn.cursor()

        # Scopes table for hierarchical session memory
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scopes (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                scope_type TEXT NOT NULL CHECK(scope_type IN ('project', 'topic', 'session')),
                name TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                source_channel TEXT NOT NULL DEFAULT 'unknown',
                created_at TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES scopes(id)
            )
        ''')

        # Detect and add missing columns on entities table
        entity_columns = self._get_table_columns('entities')
        if 'scope_id' not in entity_columns:
            cursor.execute(
                "ALTER TABLE entities ADD COLUMN scope_id TEXT DEFAULT NULL"
            )
        if 'source_channel' not in entity_columns:
            cursor.execute(
                "ALTER TABLE entities ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'legacy'"
            )

        # Detect and add missing columns on relations table
        relation_columns = self._get_table_columns('relations')
        if 'scope_id' not in relation_columns:
            cursor.execute(
                "ALTER TABLE relations ADD COLUMN scope_id TEXT DEFAULT NULL"
            )
        if 'source_channel' not in relation_columns:
            cursor.execute(
                "ALTER TABLE relations ADD COLUMN source_channel TEXT NOT NULL DEFAULT 'legacy'"
            )

        # Projects table for project-scoped knowledge graph
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                project_hash TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                project_path TEXT,
                scope_id TEXT REFERENCES scopes(id),
                domain TEXT NOT NULL DEFAULT 'coding',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(project_path)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name)'
        )

        # Create session-related indexes
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_entities_scope ON entities(scope_id)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_entities_channel ON entities(source_channel)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_relations_scope ON relations(scope_id)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_scopes_parent ON scopes(parent_id)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_scopes_type ON scopes(scope_type)'
        )

        self.conn.commit()

    def _get_table_columns(self, table_name: str) -> List[str]:
        """Get list of column names for a table"""
        cursor = self.conn.cursor()
        result = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row['name'] for row in result]

    def _build_networkx(self) -> nx.DiGraph:
        """Build NetworkX graph from database"""
        G: nx.DiGraph = nx.DiGraph()

        cursor = self.conn.cursor()

        # Add entities as nodes
        for row in cursor.execute('SELECT id, type, name, properties, scope_id, source_channel FROM entities'):
            G.add_node(
                row['id'],
                type=row['type'],
                name=row['name'],
                properties=json.loads(row['properties'] or '{}'),
                scope_id=row['scope_id'] if 'scope_id' in row.keys() else None,
                source_channel=row['source_channel'] if 'source_channel' in row.keys() else 'legacy'
            )

        # Add relations as edges
        for row in cursor.execute('SELECT source_id, target_id, relation_type, properties, scope_id, source_channel FROM relations'):
            G.add_edge(
                row['source_id'],
                row['target_id'],
                relation_type=row['relation_type'],
                properties=json.loads(row['properties'] or '{}'),
                scope_id=row['scope_id'] if 'scope_id' in row.keys() else None,
                source_channel=row['source_channel'] if 'source_channel' in row.keys() else 'legacy'
            )

        return G

    def add_entity(self, entity: Entity, scope_id: Optional[str] = None,
                   source_channel: str = 'legacy') -> Entity:
        """Add a new entity to the graph"""
        cursor = self.conn.cursor()
        now = utc_now_iso()

        entity.created_at = now
        entity.updated_at = now
        entity.version = 1
        entity.scope_id = scope_id
        entity.source_channel = source_channel

        try:
            cursor.execute('''
                INSERT INTO entities (id, type, name, properties, created_at, updated_at, version, scope_id, source_channel)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                entity.id,
                entity.type,
                entity.name,
                json.dumps(entity.properties),
                entity.created_at,
                entity.updated_at,
                entity.version,
                entity.scope_id,
                entity.source_channel
            ))

            # Record history
            cursor.execute('''
                INSERT INTO entity_history (entity_id, type, name, properties, changed_at, change_type, version)
                VALUES (?, ?, ?, ?, ?, 'created', ?)
            ''', (
                entity.id,
                entity.type,
                entity.name,
                json.dumps(entity.properties),
                now,
                entity.version
            ))

            self.conn.commit()
        except sqlite3.Error:
            logger.error("Failed to add entity %s (%s)", entity.id, entity.type)
            raise

        self.nx_graph.add_node(
            entity.id,
            type=entity.type,
            name=entity.name,
            properties=entity.properties,
            scope_id=entity.scope_id,
            source_channel=entity.source_channel
        )
        logger.info("Added entity %s:%s (%s)", entity.type, entity.name, entity.id)
        logger.debug("Entity %s created with scope_id=%s, channel=%s", entity.id, entity.scope_id, entity.source_channel)

        return entity

    def add_relation(self, relation: Relation, scope_id: Optional[str] = None,
                     source_channel: str = 'legacy') -> Relation:
        """Add a new relation to the graph"""
        cursor = self.conn.cursor()
        now = utc_now_iso()

        relation.created_at = now
        relation.version = 1
        relation.scope_id = scope_id
        relation.source_channel = source_channel

        try:
            cursor.execute('''
                INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at, version, scope_id, source_channel)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                relation.id,
                relation.source_id,
                relation.target_id,
                relation.relation_type,
                json.dumps(relation.properties),
                relation.created_at,
                relation.version,
                relation.scope_id,
                relation.source_channel
            ))

            self.conn.commit()
        except sqlite3.Error:
            logger.error("Failed to add relation %s: %s -> %s", relation.relation_type, relation.source_id, relation.target_id)
            raise

        self.nx_graph.add_edge(
            relation.source_id,
            relation.target_id,
            relation_type=relation.relation_type,
            properties=relation.properties,
            scope_id=relation.scope_id,
            source_channel=relation.source_channel
        )
        logger.info("Added relation %s: %s -> %s", relation.relation_type, relation.source_id, relation.target_id)
        logger.debug("Relation %s created with scope_id=%s, channel=%s", relation.id, relation.scope_id, relation.source_channel)

        return relation

    def update_entity(self, entity: Entity, source_channel: Optional[str] = None) -> Entity:
        """Update an existing entity and append temporal history."""
        cursor = self.conn.cursor()
        existing = self.get_entity(entity.id)
        if existing is None:
            raise KeyError(f"Entity not found: {entity.id}")

        now = utc_now_iso()
        entity.created_at = existing.created_at
        entity.updated_at = now
        entity.version = existing.version + 1
        entity.scope_id = entity.scope_id if entity.scope_id is not None else existing.scope_id
        entity.source_channel = source_channel or entity.source_channel or existing.source_channel

        cursor.execute('''
            UPDATE entities
            SET type = ?, name = ?, properties = ?, updated_at = ?, version = ?,
                scope_id = ?, source_channel = ?
            WHERE id = ?
        ''', (
            entity.type,
            entity.name,
            json.dumps(entity.properties),
            entity.updated_at,
            entity.version,
            entity.scope_id,
            entity.source_channel,
            entity.id,
        ))
        cursor.execute('''
            INSERT INTO entity_history (entity_id, type, name, properties, changed_at, change_type, version)
            VALUES (?, ?, ?, ?, ?, 'updated', ?)
        ''', (
            entity.id,
            entity.type,
            entity.name,
            json.dumps(entity.properties),
            now,
            entity.version,
        ))
        self.conn.commit()

        self.nx_graph.add_node(
            entity.id,
            type=entity.type,
            name=entity.name,
            properties=entity.properties,
            scope_id=entity.scope_id,
            source_channel=entity.source_channel,
        )
        return entity

    def get_relation(self, relation_id: str) -> Optional[Relation]:
        """Get relation by ID."""
        row = self.conn.execute(
            'SELECT * FROM relations WHERE id = ?', (relation_id,)
        ).fetchone()
        if row is None:
            return None
        return Relation(
            id=row['id'],
            source_id=row['source_id'],
            target_id=row['target_id'],
            relation_type=row['relation_type'],
            properties=json.loads(row['properties'] or '{}'),
            created_at=row['created_at'],
            version=row['version'],
            scope_id=row['scope_id'] if 'scope_id' in row.keys() else None,
            source_channel=row['source_channel'] if 'source_channel' in row.keys() else 'legacy',
        )

    def update_relation(
        self, relation: Relation, source_channel: Optional[str] = None
    ) -> Relation:
        """Update relation metadata without changing endpoints/type."""
        existing = self.get_relation(relation.id)
        if existing is None:
            raise KeyError(f"Relation not found: {relation.id}")

        relation.created_at = existing.created_at
        relation.version = existing.version + 1
        relation.scope_id = relation.scope_id if relation.scope_id is not None else existing.scope_id
        relation.source_channel = source_channel or relation.source_channel or existing.source_channel
        self.conn.execute('''
            UPDATE relations
            SET properties = ?, version = ?, scope_id = ?, source_channel = ?
            WHERE id = ?
        ''', (
            json.dumps(relation.properties),
            relation.version,
            relation.scope_id,
            relation.source_channel,
            relation.id,
        ))
        self.conn.commit()
        self.nx_graph.add_edge(
            relation.source_id,
            relation.target_id,
            relation_type=relation.relation_type,
            properties=relation.properties,
            scope_id=relation.scope_id,
            source_channel=relation.source_channel,
        )
        return relation

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID"""
        cursor = self.conn.cursor()
        row = cursor.execute('SELECT * FROM entities WHERE id = ?', (entity_id,)).fetchone()

        if row:
            return Entity(
                id=row['id'],
                type=row['type'],
                name=row['name'],
                properties=json.loads(row['properties'] or '{}'),
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                version=row['version'],
                scope_id=row['scope_id'] if 'scope_id' in row.keys() else None,
                source_channel=row['source_channel'] if 'source_channel' in row.keys() else 'legacy'
            )
        return None

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of a specific type"""
        cursor = self.conn.cursor()
        rows = cursor.execute('SELECT * FROM entities WHERE type = ?', (entity_type,)).fetchall()

        return [Entity(
            id=row['id'],
            type=row['type'],
            name=row['name'],
            properties=json.loads(row['properties'] or '{}'),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            version=row['version'],
            scope_id=row['scope_id'] if 'scope_id' in row.keys() else None,
            source_channel=row['source_channel'] if 'source_channel' in row.keys() else 'legacy'
        ) for row in rows]

    def query(self, query_str: str) -> Dict[str, Any]:
        """
        Query the knowledge graph using a simple query language.

        Query format:
          - entity:type[name] - Find entity by type and name
          - relation:type(source, target) - Find relation by type
          - path(source, target) - Find shortest path between entities
          - search:term - Search by name or properties

        Modifiers (appended with @):
          - @session:name - Filter to specific session scope
          - @project:name - Filter to specific project scope
          - @topic:name - Filter to specific topic scope
          - @channel:source - Filter by source_channel
          - @after:ISO_DATE - Filter entities created after date
          - @before:ISO_DATE - Filter entities created before date
          - @siblings - Include entities from sibling scopes

        Example: entity:task[status:active]@project:snake-game@channel:code
        """
        query_str = query_str.strip()
        logger.info("Executing query: %s", query_str)

        # Extract @ modifiers from the query
        base_query, modifiers = self._parse_modifiers(query_str)

        # Scope hierarchy query
        if base_query.startswith('scope:'):
            return self._query_scope_hierarchy(base_query, modifiers)

        # Entity query: entity:type[name]
        if base_query.startswith('entity:'):
            return self._query_entity(base_query, modifiers)

        # Relation query: relation:type
        elif base_query.startswith('relation:'):
            return self._query_relation(base_query, modifiers)

        # Path query: path(source, target)
        elif base_query.startswith('path:'):
            return self._query_path(base_query)

        # Search query: search:term
        elif base_query.startswith('search:'):
            return self._query_search(base_query, modifiers)

        return {'error': 'Unknown query format'}

    def _parse_modifiers(self, query_str: str) -> Tuple[str, Dict[str, str]]:
        """
        Parse @ modifiers from a query string.

        Returns (base_query, modifiers_dict) where modifiers_dict keys are
        modifier types (session, project, topic, channel, after, before, siblings).
        """
        modifiers: Dict[str, str] = {}
        # Split on @ but preserve the base query (first segment)
        parts = query_str.split('@')
        base_query = parts[0].strip()

        for part in parts[1:]:
            part = part.strip()
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.lower()
                if key in ('session', 'project', 'topic', 'channel', 'after', 'before'):
                    modifiers[key] = value
            elif part.lower() == 'siblings':
                modifiers['siblings'] = 'true'

        return base_query, modifiers

    def _resolve_scope_filter(
        self, modifiers: Dict[str, str]
    ) -> Optional[List[Optional[str]]]:
        """
        Resolve scope modifiers into a list of visible scope IDs.

        Returns None if no scope filtering is needed (return all).
        Returns a list of scope IDs (including None for global) to filter by.
        """
        scope_filter: Optional[List[Optional[str]]] = None

        # Check for scope-type modifiers
        for scope_type in ('session', 'project', 'topic'):
            if scope_type in modifiers:
                scope = self.scope_manager.find_scope_by_name(
                    modifiers[scope_type], scope_type=scope_type
                )
                if scope is None:
                    # Scope not found; return empty filter
                    return []
                visible_ids = self.scope_manager.resolve_visible_scope_ids(scope.id)
                if scope_filter is None:
                    scope_filter = visible_ids
                else:
                    # Intersect with existing filter
                    scope_filter = [s for s in scope_filter if s in visible_ids]
                break

        # Expand to include siblings if requested
        if 'siblings' in modifiers:
            for scope_type in ('session', 'project', 'topic'):
                if scope_type in modifiers:
                    scope = self.scope_manager.find_scope_by_name(
                        modifiers[scope_type], scope_type=scope_type
                    )
                    if scope is not None:
                        siblings = self.scope_manager.get_siblings(scope.id)
                        for sibling in siblings:
                            sibling_ids = self.scope_manager.resolve_visible_scope_ids(
                                sibling.id
                            )
                            for sid in sibling_ids:
                                if scope_filter is None:
                                    scope_filter = [sid]
                                elif sid not in scope_filter:
                                    scope_filter.append(sid)
                    break

        return scope_filter

    def _build_where_clauses(
        self,
        modifiers: Dict[str, str],
        table_alias: str = 'e',
    ) -> Tuple[List[str], List[Any]]:
        """
        Build WHERE clause fragments and params from modifiers.

        Returns (clauses, params).
        """
        clauses: List[str] = []
        params: List[Any] = []

        # Scope filtering
        scope_filter = self._resolve_scope_filter(modifiers)
        if scope_filter is not None:
            if len(scope_filter) == 0:
                # No matching scope -- force no results
                clauses.append(f'{table_alias}.scope_id IS NULL AND 1=0')
            else:
                # Build IN clause handling NULL for global scope
                has_null = None in scope_filter
                non_null = [s for s in scope_filter if s is not None]

                if has_null and non_null:
                    placeholders = ','.join('?' * len(non_null))
                    clauses.append(
                        f'({table_alias}.scope_id IS NULL OR {table_alias}.scope_id IN ({placeholders}))'
                    )
                    params.extend(non_null)
                elif has_null:
                    clauses.append(f'{table_alias}.scope_id IS NULL')
                else:
                    placeholders = ','.join('?' * len(non_null))
                    clauses.append(
                        f'{table_alias}.scope_id IN ({placeholders})'
                    )
                    params.extend(non_null)

        # Channel filtering
        if 'channel' in modifiers:
            clauses.append(f'{table_alias}.source_channel = ?')
            params.append(modifiers['channel'])

        # Temporal filtering
        if 'after' in modifiers:
            clauses.append(f'{table_alias}.created_at > ?')
            params.append(modifiers['after'])

        if 'before' in modifiers:
            clauses.append(f'{table_alias}.created_at < ?')
            params.append(modifiers['before'])

        return clauses, params

    def _query_scope_hierarchy(
        self, query_str: str, modifiers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Handle scope:name queries returning hierarchy tree with entity counts."""
        name = query_str.replace('scope:', '').strip()

        scope = self.scope_manager.find_scope_by_name(name)
        if scope is None:
            return {'type': 'scope_query', 'error': f'Scope "{name}" not found'}

        # Build hierarchy tree
        def build_tree(s: Scope) -> Dict[str, Any]:
            cursor = self.conn.cursor()
            entity_count = cursor.execute(
                'SELECT COUNT(*) FROM entities WHERE scope_id = ?', (s.id,)
            ).fetchone()[0]

            children = self.scope_manager.get_children(s.id)
            return {
                'id': s.id,
                'name': s.name,
                'type': s.scope_type,
                'entity_count': entity_count,
                'children': [build_tree(c) for c in children],
            }

        tree = build_tree(scope)
        return {'type': 'scope_query', 'scope': tree}

    def _query_entity(
        self, query_str: str, modifiers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Handle entity queries with optional scope/channel/temporal filters"""
        if modifiers is None:
            modifiers = {}

        # Parse entity:type[name]
        parts = query_str.replace('entity:', '').split('[')
        type_part = parts[0]
        name_part = parts[1].rstrip(']') if len(parts) > 1 else None

        cursor = self.conn.cursor()

        # Build base conditions
        conditions = ['e.type = ?']
        params: List[Any] = [type_part]

        if name_part:
            if '*' in name_part:
                pattern = name_part.replace('*', '%')
                conditions.append('e.name LIKE ?')
                params.append(pattern)
            else:
                conditions.append('e.name = ?')
                params.append(name_part)

        # Apply modifier-based filters
        mod_clauses, mod_params = self._build_where_clauses(modifiers, table_alias='e')
        conditions.extend(mod_clauses)
        params.extend(mod_params)

        where = ' AND '.join(conditions)
        rows = cursor.execute(
            f'SELECT e.* FROM entities e WHERE {where}', params
        ).fetchall()

        entities = [{
            'id': row['id'],
            'type': row['type'],
            'name': row['name'],
            'properties': json.loads(row['properties'] or '{}'),
            'version': row['version'],
            'scope_id': row['scope_id'] if 'scope_id' in row.keys() else None,
            'source_channel': row['source_channel'] if 'source_channel' in row.keys() else 'legacy',
        } for row in rows]

        logger.info("Entity query returned %d results", len(entities))
        return {'type': 'entity_query', 'results': entities, 'count': len(entities)}

    def _query_relation(
        self, query_str: str, modifiers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Handle relation queries with optional scope/channel/temporal filters"""
        if modifiers is None:
            modifiers = {}

        # Parse relation:type(source_id, target_id)
        parts = query_str.replace('relation:', '').split('(')
        rel_type = parts[0]

        cursor = self.conn.cursor()

        conditions = ['r.relation_type = ?']
        params: List[Any] = [rel_type]

        if len(parts) > 1:
            args = parts[1].rstrip(')').split(',')
            conditions.append('r.source_id = ?')
            params.append(args[0].strip())
            conditions.append('r.target_id = ?')
            params.append(args[1].strip())

        # Apply modifier-based filters
        mod_clauses, mod_params = self._build_where_clauses(modifiers, table_alias='r')
        conditions.extend(mod_clauses)
        params.extend(mod_params)

        where = ' AND '.join(conditions)
        rows = cursor.execute(
            f'SELECT r.* FROM relations r WHERE {where}', params
        ).fetchall()

        relations = [{
            'id': row['id'],
            'source_id': row['source_id'],
            'target_id': row['target_id'],
            'type': row['relation_type'],
            'properties': json.loads(row['properties'] or '{}'),
            'version': row['version'],
            'scope_id': row['scope_id'] if 'scope_id' in row.keys() else None,
            'source_channel': row['source_channel'] if 'source_channel' in row.keys() else 'legacy',
        } for row in rows]

        logger.info("Relation query returned %d results", len(relations))
        return {'type': 'relation_query', 'results': relations, 'count': len(relations)}

    def _query_path(self, query_str: str) -> Dict[str, Any]:
        """Find path between two entities"""
        # Parse path(source_name, target_name)
        parts = query_str.replace('path:', '').strip().lstrip('(').rstrip(')').split(',')
        source_name, target_name = parts[0].strip(), parts[1].strip()

        # Find entity IDs
        source_id = self._find_entity_id_by_name(source_name)
        target_id = self._find_entity_id_by_name(target_name)

        if not source_id or not target_id:
            return {'error': 'Entity not found', 'source': source_name, 'target': target_name}

        try:
            path = nx.shortest_path(self.nx_graph, source_id, target_id)
            edges = []
            for i in range(len(path) - 1):
                edge_data = self.nx_graph.get_edge_data(path[i], path[i+1])
                edges.append({
                    'from': path[i],
                    'to': path[i+1],
                    'relation': edge_data.get('relation_type', 'connected_to')
                })

            return {
                'type': 'path',
                'path': path,
                'edges': edges,
                'length': len(path) - 1
            }
        except nx.NetworkXNoPath:
            return {'error': 'No path found', 'source': source_name, 'target': target_name}

    def _query_search(
        self, query_str: str, modifiers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Search entities by name or property content with optional filters"""
        if modifiers is None:
            modifiers = {}

        term = query_str.replace('search:', '').strip()

        cursor = self.conn.cursor()
        pattern = f'%{term}%'

        conditions = ['(e.name LIKE ? OR e.properties LIKE ?)']
        params: List[Any] = [pattern, pattern]

        # Apply modifier-based filters
        mod_clauses, mod_params = self._build_where_clauses(modifiers, table_alias='e')
        conditions.extend(mod_clauses)
        params.extend(mod_params)

        where = ' AND '.join(conditions)
        rows = cursor.execute(
            f'SELECT e.* FROM entities e WHERE {where}', params
        ).fetchall()

        entities = [{
            'id': row['id'],
            'type': row['type'],
            'name': row['name'],
            'properties': json.loads(row['properties'] or '{}'),
            'scope_id': row['scope_id'] if 'scope_id' in row.keys() else None,
            'source_channel': row['source_channel'] if 'source_channel' in row.keys() else 'legacy',
        } for row in rows]

        logger.info("Search query '%s' returned %d results", term, len(entities))
        return {'type': 'search', 'term': term, 'results': entities, 'count': len(entities)}

    def _find_entity_id_by_name(self, name: str) -> Optional[str]:
        """Find entity ID by name"""
        cursor = self.conn.cursor()
        row = cursor.execute('SELECT id FROM entities WHERE name = ?', (name,)).fetchone()
        return row['id'] if row else None

    def get_entity_history(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get temporal history of an entity"""
        cursor = self.conn.cursor()
        rows = cursor.execute('''
            SELECT * FROM entity_history
            WHERE entity_id = ?
            ORDER BY version DESC
        ''', (entity_id,)).fetchall()

        return [{
            'entity_id': row['entity_id'],
            'type': row['type'],
            'name': row['name'],
            'properties': json.loads(row['properties'] or '{}'),
            'changed_at': row['changed_at'],
            'change_type': row['change_type'],
            'version': row['version']
        } for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics including scope distribution"""
        cursor = self.conn.cursor()

        entity_count = cursor.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
        relation_count = cursor.execute('SELECT COUNT(*) FROM relations').fetchone()[0]

        type_counts = {}
        for row in cursor.execute('SELECT type, COUNT(*) FROM entities GROUP BY type'):
            type_counts[row['type']] = row[1]

        stats = {
            'entities': entity_count,
            'relations': relation_count,
            'by_type': type_counts,
            'density': nx.density(self.nx_graph),
            'connected_components': nx.number_weakly_connected_components(self.nx_graph),
        }

        # Add scope distribution
        try:
            scope_type_counts = {}
            for row in cursor.execute(
                'SELECT scope_type, COUNT(*) FROM scopes GROUP BY scope_type'
            ):
                scope_type_counts[row['scope_type']] = row[1]

            entity_scope_counts = {}
            for row in cursor.execute('''
                SELECT s.name, s.scope_type, COUNT(e.id) as cnt
                FROM scopes s
                LEFT JOIN entities e ON e.scope_id = s.id
                GROUP BY s.id
            '''):
                entity_scope_counts[row['name']] = {
                    'scope_type': row['scope_type'],
                    'entity_count': row['cnt'],
                }

            stats['scopes'] = {
                'by_type': scope_type_counts,
                'entity_counts_per_scope': entity_scope_counts,
            }
        except sqlite3.OperationalError as e:
            # Scopes table might not exist yet in edge migration cases
            logger.error("Database error reading scope stats: %s", e)
            stats['scopes'] = {'by_type': {}, 'entity_counts_per_scope': {}}

        return stats

    # -- Scope convenience delegates --

    def create_scope(
        self,
        scope_type: str,
        name: str,
        parent_id: Optional[str] = None,
        source_channel: str = 'unknown',
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Scope:
        """Create a new scope. Delegates to ScopeManager."""
        return self.scope_manager.create_scope(
            scope_type=scope_type,
            name=name,
            parent_id=parent_id,
            source_channel=source_channel,
            metadata=metadata,
        )

    def get_scope(self, scope_id: str) -> Optional[Scope]:
        """Get a scope by ID. Delegates to ScopeManager."""
        return self.scope_manager.get_scope(scope_id)

    def close(self):
        """Close database connection"""
        self.conn.close()

    # -- Project registry helpers --

    def register_project(
        self,
        project_hash: str,
        project_name: str,
        project_path: str,
        domain: str = "coding",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a project and return its scope_id. Idempotent."""
        cursor = self.conn.cursor()

        existing = cursor.execute(
            "SELECT scope_id FROM projects WHERE project_hash = ?",
            (project_hash,),
        ).fetchone()
        if existing:
            return existing["scope_id"]

        now = utc_now_iso()

        scope = self.create_scope(
            scope_type="project",
            name=project_name,
            source_channel="auto-detect",
            metadata=metadata or {},
        )

        cursor.execute(
            """INSERT INTO projects
               (project_hash, project_name, project_path, scope_id, domain, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_hash,
                project_name,
                project_path,
                scope.id,
                domain,
                now,
                now,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        logger.info("Registered project %s (%s)", project_name, project_hash[:12])
        return scope.id

    def get_project_by_hash(self, project_hash: str) -> Optional[Dict[str, Any]]:
        """Get project details by hash."""
        row = self.conn.execute(
            "SELECT * FROM projects WHERE project_hash = ?",
            (project_hash,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get project details by name."""
        row = self.conn.execute(
            "SELECT * FROM projects WHERE project_name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all registered projects with entity counts."""
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """SELECT p.*, COUNT(e.id) AS entity_count
               FROM projects p
               LEFT JOIN entities e ON e.scope_id = p.scope_id
               GROUP BY p.project_hash
               ORDER BY p.updated_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_project_scope_id(self, project_path: str) -> Optional[str]:
        """Look up scope_id for a project by its canonical path."""
        row = self.conn.execute(
            "SELECT scope_id FROM projects WHERE project_path = ?",
            (project_path,),
        ).fetchone()
        return row["scope_id"] if row else None

    def unregister_project(self, project_hash: str) -> bool:
        """Remove a project registration (does not delete entities)."""
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT scope_id FROM projects WHERE project_hash = ?",
            (project_hash,),
        ).fetchone()
        if row is None:
            return False
        cursor.execute(
            "DELETE FROM projects WHERE project_hash = ?",
            (project_hash,),
        )
        self.conn.commit()
        logger.info("Unregistered project %s", project_hash[:12])
        return True


def main():
    """Deprecated: use mnemosyne.graph.cli:main instead."""
    from mnemosyne.graph.cli import main as cli_main
    cli_main()


if __name__ == '__main__':
    main()
