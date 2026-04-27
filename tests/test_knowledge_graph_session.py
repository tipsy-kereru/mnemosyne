"""
Tests for KnowledgeGraph session features: entities with scope, extended query
language, backward compatibility, and database migration.
"""

import sqlite3

import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph, Entity, Relation


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_kg.db")


@pytest.fixture
def kg(db_path):
    """Create a KnowledgeGraph instance with a temporary database."""
    graph = KnowledgeGraph(db_path=db_path)
    yield graph
    graph.close()


@pytest.fixture
def hierarchy(kg):
    """Create a project -> topic -> session hierarchy."""
    project = kg.create_scope('project', 'Snake Game')
    topic = kg.create_scope('topic', 'Rendering', parent_id=project.id)
    session = kg.create_scope('session', 'Bug Fix', parent_id=topic.id)
    return project, topic, session


# -- Entity Scope Assignment --


class TestEntityScopeAssignment:
    def test_add_entity_with_scope(self, kg, hierarchy):
        project, topic, session = hierarchy
        e = Entity(id='e1', type='task', name='Fix Bug', properties={},
                    created_at='', updated_at='')
        result = kg.add_entity(e, scope_id=session.id, source_channel='code')
        assert result.scope_id == session.id
        assert result.source_channel == 'code'

    def test_entity_scope_persisted(self, kg, hierarchy):
        project, topic, session = hierarchy
        e = Entity(id='e2', type='task', name='Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e, scope_id=session.id, source_channel='discord')
        retrieved = kg.get_entity('e2')
        assert retrieved.scope_id == session.id
        assert retrieved.source_channel == 'discord'

    def test_add_entity_without_scope(self, kg):
        e = Entity(id='e3', type='task', name='Global Task', properties={},
                    created_at='', updated_at='')
        result = kg.add_entity(e)
        assert result.scope_id is None
        assert result.source_channel == 'legacy'

    def test_add_entity_default_channel(self, kg, hierarchy):
        _, _, session = hierarchy
        e = Entity(id='e4', type='note', name='N', properties={},
                    created_at='', updated_at='')
        result = kg.add_entity(e, scope_id=session.id)
        assert result.source_channel == 'legacy'


class TestRelationScopeAssignment:
    def test_add_relation_with_scope(self, kg, hierarchy):
        _, _, session = hierarchy
        e1 = Entity(id='r_e1', type='task', name='A', properties={},
                      created_at='', updated_at='')
        e2 = Entity(id='r_e2', type='task', name='B', properties={},
                      created_at='', updated_at='')
        kg.add_entity(e1, scope_id=session.id)
        kg.add_entity(e2, scope_id=session.id)

        rel = Relation(id='rel1', source_id='r_e1', target_id='r_e2',
                        relation_type='depends_on', properties={},
                        created_at='')
        result = kg.add_relation(rel, scope_id=session.id, source_channel='code')
        assert result.scope_id == session.id
        assert result.source_channel == 'code'

    def test_add_relation_without_scope(self, kg):
        e1 = Entity(id='r2_e1', type='task', name='A', properties={},
                      created_at='', updated_at='')
        e2 = Entity(id='r2_e2', type='task', name='B', properties={},
                      created_at='', updated_at='')
        kg.add_entity(e1)
        kg.add_entity(e2)

        rel = Relation(id='rel2', source_id='r2_e1', target_id='r2_e2',
                        relation_type='depends_on', properties={},
                        created_at='')
        result = kg.add_relation(rel)
        assert result.scope_id is None
        assert result.source_channel == 'legacy'


# -- Extended Query Language --


class TestQueryModifiers:
    def _seed_entities(self, kg, hierarchy):
        project, topic, session = hierarchy
        # Global entity
        kg.add_entity(
            Entity(id='g1', type='task', name='Global Task', properties={},
                    created_at='', updated_at=''),
        )
        # Entity in project scope
        kg.add_entity(
            Entity(id='p1', type='task', name='Project Task', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id, source_channel='code',
        )
        # Entity in topic scope
        kg.add_entity(
            Entity(id='t1', type='task', name='Topic Task', properties={},
                    created_at='', updated_at=''),
            scope_id=topic.id, source_channel='discord',
        )
        # Entity in session scope
        kg.add_entity(
            Entity(id='s1', type='task', name='Session Task', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id, source_channel='slack',
        )
        # Different type entity
        kg.add_entity(
            Entity(id='n1', type='note', name='A Note', properties={},
                    created_at='', updated_at=''),
            scope_id=topic.id,
        )

    def test_query_without_modifiers_returns_all(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        result = kg.query('entity:task')
        assert result['count'] == 4  # all tasks regardless of scope

    def test_query_at_project(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        project, topic, session = hierarchy
        result = kg.query('entity:task@project:Snake Game')
        # Visible from project: global, project, topic, session entities
        ids = {e['id'] for e in result['results']}
        assert 'g1' in ids
        assert 'p1' in ids
        assert 't1' in ids
        assert 's1' in ids

    def test_query_at_session(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        result = kg.query('entity:task@session:Bug Fix')
        ids = {e['id'] for e in result['results']}
        # Session sees: global, project, topic, session entities
        assert 'g1' in ids
        assert 'p1' in ids
        assert 't1' in ids
        assert 's1' in ids

    def test_query_at_channel(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        result = kg.query('entity:task@channel:discord')
        assert result['count'] == 1
        assert result['results'][0]['id'] == 't1'

    def test_query_at_after(self, kg, hierarchy):
        """Temporal filtering with @after."""
        project, _, _ = hierarchy
        kg.add_entity(
            Entity(id='early', type='event', name='Early', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )
        kg.add_entity(
            Entity(id='late', type='event', name='Late', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )
        # Update 'early' to have an older timestamp
        cursor = kg.conn.cursor()
        cursor.execute(
            "UPDATE entities SET created_at = '2020-01-01T00:00:00' WHERE id = 'early'"
        )
        cursor.execute(
            "UPDATE entities SET created_at = '2030-01-01T00:00:00' WHERE id = 'late'"
        )
        kg.conn.commit()

        result = kg.query('entity:event@after:2025-01-01T00:00:00')
        assert result['count'] == 1
        assert result['results'][0]['id'] == 'late'

    def test_query_at_before(self, kg, hierarchy):
        project, _, _ = hierarchy
        kg.add_entity(
            Entity(id='old', type='bug', name='Old Bug', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )
        kg.add_entity(
            Entity(id='new', type='bug', name='New Bug', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )
        cursor = kg.conn.cursor()
        cursor.execute(
            "UPDATE entities SET created_at = '2020-01-01T00:00:00' WHERE id = 'old'"
        )
        cursor.execute(
            "UPDATE entities SET created_at = '2030-01-01T00:00:00' WHERE id = 'new'"
        )
        kg.conn.commit()

        result = kg.query('entity:bug@before:2025-01-01T00:00:00')
        assert result['count'] == 1
        assert result['results'][0]['id'] == 'old'

    def test_query_at_siblings(self, kg, hierarchy):
        project, topic, session = hierarchy
        # Create sibling sessions
        session2 = kg.create_scope('session', 'Refactor', parent_id=topic.id)

        kg.add_entity(
            Entity(id='s1_e', type='task', name='S1 Task', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )
        kg.add_entity(
            Entity(id='s2_e', type='task', name='S2 Task', properties={},
                    created_at='', updated_at=''),
            scope_id=session2.id,
        )

        result = kg.query('entity:task@session:Bug Fix@siblings')
        ids = {e['id'] for e in result['results']}
        # Should see: session's own task + sibling session's task + ancestors + global
        assert 's1_e' in ids
        assert 's2_e' in ids

    def test_query_combined_modifiers(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        result = kg.query('entity:task@project:Snake Game@channel:discord')
        assert result['count'] == 1
        assert result['results'][0]['id'] == 't1'

    def test_query_scope_not_found(self, kg, hierarchy):
        self._seed_entities(kg, hierarchy)
        result = kg.query('entity:task@project:nonexistent')
        assert result['count'] == 0

    def test_search_with_scope(self, kg, hierarchy):
        project, topic, session = hierarchy
        kg.add_entity(
            Entity(id='x1', type='task', name='Auth Login', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )
        kg.add_entity(
            Entity(id='x2', type='task', name='Auth Logout', properties={},
                    created_at='', updated_at=''),
        )
        result = kg.query('search:Auth@session:Bug Fix')
        assert result['count'] == 2  # both visible from session scope

    def test_search_with_channel(self, kg, hierarchy):
        project, _, _ = hierarchy
        kg.add_entity(
            Entity(id='y1', type='task', name='Deploy Task', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id, source_channel='code',
        )
        kg.add_entity(
            Entity(id='y2', type='task', name='Deploy Note', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id, source_channel='slack',
        )
        result = kg.query('search:Deploy@channel:code')
        assert result['count'] == 1
        assert result['results'][0]['id'] == 'y1'

    def test_relation_query_with_scope(self, kg, hierarchy):
        project, _, _ = hierarchy
        e1 = Entity(id='rq1', type='task', name='A', properties={},
                      created_at='', updated_at='')
        e2 = Entity(id='rq2', type='task', name='B', properties={},
                      created_at='', updated_at='')
        kg.add_entity(e1, scope_id=project.id)
        kg.add_entity(e2, scope_id=project.id)

        rel = Relation(id='rq_r1', source_id='rq1', target_id='rq2',
                        relation_type='depends_on', properties={},
                        created_at='')
        kg.add_relation(rel, scope_id=project.id)

        result = kg.query('relation:depends_on@project:Snake Game')
        assert result['count'] == 1


# -- Scope Hierarchy Query --


class TestScopeHierarchyQuery:
    def test_scope_query(self, kg, hierarchy):
        project, topic, session = hierarchy
        kg.add_entity(
            Entity(id='h1', type='task', name='Task', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )
        kg.add_entity(
            Entity(id='h2', type='note', name='Note', properties={},
                    created_at='', updated_at=''),
            scope_id=topic.id,
        )
        kg.add_entity(
            Entity(id='h3', type='bug', name='Bug', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )

        result = kg.query('scope:Snake Game')
        assert result['type'] == 'scope_query'
        tree = result['scope']
        assert tree['name'] == 'Snake Game'
        assert tree['entity_count'] == 1
        assert len(tree['children']) == 1  # topic
        assert tree['children'][0]['name'] == 'Rendering'
        assert tree['children'][0]['entity_count'] == 1
        assert len(tree['children'][0]['children']) == 1  # session
        assert tree['children'][0]['children'][0]['entity_count'] == 1

    def test_scope_query_not_found(self, kg):
        result = kg.query('scope:nonexistent')
        assert 'error' in result


# -- Backward Compatibility --


class TestBackwardCompatibility:
    def test_existing_entity_query_works(self, kg):
        """Queries without @ modifiers work unchanged."""
        e = Entity(id='bc1', type='task', name='Legacy Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e)

        result = kg.query('entity:task')
        assert result['count'] == 1
        assert result['results'][0]['name'] == 'Legacy Task'

    def test_existing_entity_by_name_query(self, kg):
        e = Entity(id='bc2', type='task', name='Specific Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e)

        result = kg.query('entity:task[Specific Task]')
        assert result['count'] == 1

    def test_existing_wildcard_query(self, kg):
        e = Entity(id='bc3', type='task', name='Auth Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e)

        result = kg.query('entity:task[Auth*]')
        assert result['count'] == 1

    def test_existing_relation_query(self, kg):
        e1 = Entity(id='bc4', type='task', name='A', properties={},
                      created_at='', updated_at='')
        e2 = Entity(id='bc5', type='task', name='B', properties={},
                      created_at='', updated_at='')
        kg.add_entity(e1)
        kg.add_entity(e2)

        rel = Relation(id='bc_r1', source_id='bc4', target_id='bc5',
                        relation_type='depends_on', properties={},
                        created_at='')
        kg.add_relation(rel)

        result = kg.query('relation:depends_on')
        assert result['count'] == 1

    def test_existing_search_query(self, kg):
        e = Entity(id='bc6', type='task', name='Searchable Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e)

        result = kg.query('search:Searchable')
        assert result['count'] == 1

    def test_path_query_still_works(self, kg):
        e1 = Entity(id='bc7', type='task', name='Node1', properties={},
                      created_at='', updated_at='')
        e2 = Entity(id='bc8', type='task', name='Node2', properties={},
                      created_at='', updated_at='')
        kg.add_entity(e1)
        kg.add_entity(e2)

        rel = Relation(id='bc_r2', source_id='bc7', target_id='bc8',
                        relation_type='connects', properties={},
                        created_at='')
        kg.add_relation(rel)

        result = kg.query('path:Node1,Node2')
        assert result['type'] == 'path'
        assert result['length'] == 1

    def test_add_entity_without_new_params(self, kg):
        """Old calling convention still works."""
        e = Entity(id='bc9', type='task', name='Old Style', properties={},
                    created_at='', updated_at='')
        result = kg.add_entity(e)
        assert result.scope_id is None
        assert result.source_channel == 'legacy'


# -- Database Migration --


class TestDatabaseMigration:
    def test_migration_preserves_data(self, tmp_path):
        """Opening an existing DB preserves data and adds new columns."""
        db_path = str(tmp_path / "migration_test.db")

        # Create a DB with the old schema (no session columns)
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER DEFAULT 1
            )
        ''')
        conn.execute('''
            INSERT INTO entities VALUES
                ('old1', 'task', 'Old Task', '{}', '2020-01-01', '2020-01-01', 1)
        ''')
        conn.commit()
        conn.close()

        # Open with new KnowledgeGraph - should migrate
        kg = KnowledgeGraph(db_path=db_path)
        entity = kg.get_entity('old1')
        assert entity is not None
        assert entity.name == 'Old Task'
        assert entity.scope_id is None  # Migrated column default
        assert entity.source_channel == 'legacy'  # Migrated column default

        # Verify new tables exist
        cursor = kg.conn.cursor()
        tables = [row['name'] for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert 'scopes' in tables

        kg.close()

    def test_migration_idempotent(self, tmp_path):
        """Opening the same DB twice does not error."""
        db_path = str(tmp_path / "idempotent_test.db")

        kg1 = KnowledgeGraph(db_path=db_path)
        kg1.create_scope('project', 'P1')
        kg1.close()

        kg2 = KnowledgeGraph(db_path=db_path)
        scope = kg2.scope_manager.find_scope_by_name('P1')
        assert scope is not None
        kg2.close()


# -- NetworkX Sync --


class TestNetworkXSync:
    def test_scope_id_in_node_attributes(self, kg, hierarchy):
        _, _, session = hierarchy
        e = Entity(id='nx1', type='task', name='NX Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e, scope_id=session.id, source_channel='code')

        node_data = kg.nx_graph.nodes['nx1']
        assert node_data['scope_id'] == session.id
        assert node_data['source_channel'] == 'code'

    def test_scope_id_in_edge_attributes(self, kg, hierarchy):
        _, _, session = hierarchy
        kg.add_entity(
            Entity(id='nx_e1', type='task', name='A', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )
        kg.add_entity(
            Entity(id='nx_e2', type='task', name='B', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )
        rel = Relation(id='nx_r1', source_id='nx_e1', target_id='nx_e2',
                        relation_type='depends_on', properties={},
                        created_at='')
        kg.add_relation(rel, scope_id=session.id)

        edge_data = kg.nx_graph.get_edge_data('nx_e1', 'nx_e2')
        assert edge_data['scope_id'] == session.id


# -- Stats --


class TestStats:
    def test_stats_includes_scopes(self, kg, hierarchy):
        project, topic, session = hierarchy
        kg.add_entity(
            Entity(id='st1', type='task', name='T', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id,
        )

        stats = kg.get_stats()
        assert 'scopes' in stats
        assert stats['scopes']['by_type']['project'] == 1
        assert stats['scopes']['by_type']['topic'] == 1
        assert stats['scopes']['by_type']['session'] == 1


# -- Convenience Delegates --


class TestConvenienceDelegates:
    def test_create_scope_delegate(self, kg):
        scope = kg.create_scope('project', 'Via Delegate')
        assert scope.name == 'Via Delegate'
        assert scope.scope_type == 'project'

    def test_get_scope_delegate(self, kg):
        scope = kg.create_scope('project', 'P')
        retrieved = kg.get_scope(scope.id)
        assert retrieved is not None
        assert retrieved.name == 'P'

    def test_get_scope_delegate_not_found(self, kg):
        assert kg.get_scope('nonexistent') is None


# -- Edge Cases --


class TestEdgeCases:
    def test_query_entity_with_name_no_results(self, kg):
        result = kg.query('entity:task[Nonexistent]')
        assert result['count'] == 0

    def test_query_empty_string(self, kg):
        result = kg.query('')
        assert 'error' in result

    def test_get_entities_by_type_with_scope(self, kg, hierarchy):
        _, _, session = hierarchy
        kg.add_entity(
            Entity(id='et1', type='task', name='T1', properties={},
                    created_at='', updated_at=''),
            scope_id=session.id,
        )
        kg.add_entity(
            Entity(id='et2', type='task', name='T2', properties={},
                    created_at='', updated_at=''),
        )
        entities = kg.get_entities_by_type('task')
        assert len(entities) == 2
        scoped = [e for e in entities if e.scope_id == session.id]
        assert len(scoped) == 1

    def test_multiple_modifiers_no_scope(self, kg, hierarchy):
        """Channel + temporal without scope filter."""
        project, _, _ = hierarchy
        kg.add_entity(
            Entity(id='ec1', type='task', name='EC Task', properties={},
                    created_at='', updated_at=''),
            scope_id=project.id, source_channel='code',
        )
        cursor = kg.conn.cursor()
        cursor.execute(
            "UPDATE entities SET created_at = '2020-01-01T00:00:00' WHERE id = 'ec1'"
        )
        kg.conn.commit()

        result = kg.query('entity:task@channel:code@after:2019-01-01T00:00:00')
        assert result['count'] == 1
