"""
Tests for ScopeManager: CRUD, hierarchy validation, tree traversal.
"""


import pytest

from mnemosyne.graph.knowledge_graph import KnowledgeGraph, Entity


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
def sm(kg):
    """Return the ScopeManager from a live KnowledgeGraph."""
    return kg.scope_manager


# -- Scope CRUD Tests --


class TestScopeCreation:
    def test_create_project(self, sm):
        scope = sm.create_scope('project', 'Snake Game')
        assert scope.id is not None
        assert scope.scope_type == 'project'
        assert scope.name == 'Snake Game'
        assert scope.parent_id is None
        assert scope.source_channel == 'unknown'

    def test_create_project_with_parent_fails(self, sm):
        project = sm.create_scope('project', 'Root')
        with pytest.raises(ValueError, match="parent_id = None"):
            sm.create_scope('project', 'Sub-Project', parent_id=project.id)

    def test_create_topic(self, sm):
        project = sm.create_scope('project', 'Snake Game')
        topic = sm.create_scope('topic', 'Rendering', parent_id=project.id)
        assert topic.scope_type == 'topic'
        assert topic.parent_id == project.id

    def test_create_topic_without_parent_fails(self, sm):
        with pytest.raises(ValueError, match="parent_id"):
            sm.create_scope('topic', 'Orphan Topic')

    def test_create_session(self, sm):
        project = sm.create_scope('project', 'Snake Game')
        topic = sm.create_scope('topic', 'Rendering', parent_id=project.id)
        session = sm.create_scope('session', 'Bug Fix', parent_id=topic.id)
        assert session.scope_type == 'session'
        assert session.parent_id == topic.id

    def test_create_session_under_session(self, sm):
        """Sessions can nest infinitely under other sessions."""
        project = sm.create_scope('project', 'Snake Game')
        topic = sm.create_scope('topic', 'Rendering', parent_id=project.id)
        s1 = sm.create_scope('session', 'S1', parent_id=topic.id)
        s2 = sm.create_scope('session', 'S2', parent_id=s1.id)
        s3 = sm.create_scope('session', 'S3', parent_id=s2.id)
        assert s3.parent_id == s2.id
        assert sm.get_ancestors(s3.id)[0].id == s2.id

    def test_create_session_without_parent_fails(self, sm):
        with pytest.raises(ValueError, match="parent_id"):
            sm.create_scope('session', 'Orphan Session')

    def test_create_session_under_project_fails(self, sm):
        project = sm.create_scope('project', 'P')
        with pytest.raises(ValueError, match="topic or session"):
            sm.create_scope('session', 'S', parent_id=project.id)

    def test_create_topic_under_topic_fails(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        with pytest.raises(ValueError, match="project"):
            sm.create_scope('topic', 'T2', parent_id=topic.id)

    def test_invalid_scope_type(self, sm):
        with pytest.raises(ValueError, match="Invalid scope_type"):
            sm.create_scope('invalid', 'X')

    def test_nonexistent_parent(self, sm):
        with pytest.raises(ValueError, match="not found"):
            sm.create_scope('topic', 'T', parent_id='nonexistent')

    def test_create_with_metadata_and_channel(self, sm):
        project = sm.create_scope(
            'project', 'P',
            source_channel='discord',
            metadata={'priority': 'high'}
        )
        assert project.source_channel == 'discord'
        assert project.metadata == {'priority': 'high'}


class TestScopeRetrieval:
    def test_get_scope(self, sm):
        created = sm.create_scope('project', 'P')
        retrieved = sm.get_scope(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == 'P'

    def test_get_scope_not_found(self, sm):
        assert sm.get_scope('nonexistent') is None

    def test_find_scope_by_name(self, sm):
        sm.create_scope('project', 'Snake Game')
        found = sm.find_scope_by_name('Snake Game')
        assert found is not None
        assert found.scope_type == 'project'

    def test_find_scope_by_name_with_type_filter(self, sm):
        sm.create_scope('project', 'Game')
        project = sm.create_scope('project', 'P1')
        sm.create_scope('topic', 'Game', parent_id=project.id)
        # 'Game' as topic
        found = sm.find_scope_by_name('Game', scope_type='topic')
        assert found is not None
        assert found.scope_type == 'topic'

    def test_find_scope_by_name_not_found(self, sm):
        assert sm.find_scope_by_name('nonexistent') is None


class TestScopeDeletion:
    def test_delete_scope_leaf(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        assert sm.delete_scope(topic.id) is True
        assert sm.get_scope(topic.id) is None

    def test_delete_scope_with_children_no_cascade(self, sm):
        project = sm.create_scope('project', 'P')
        sm.create_scope('topic', 'T', parent_id=project.id)
        with pytest.raises(ValueError, match="children"):
            sm.delete_scope(project.id)

    def test_delete_scope_with_cascade(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        session = sm.create_scope('session', 'S', parent_id=topic.id)
        assert sm.delete_scope(project.id, cascade=True) is True
        assert sm.get_scope(project.id) is None
        assert sm.get_scope(topic.id) is None
        assert sm.get_scope(session.id) is None

    def test_delete_scope_cascade_reassigns_entities(self, sm, kg):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)

        e = Entity(id='e1', type='task', name='Task', properties={},
                    created_at='', updated_at='')
        kg.add_entity(e, scope_id=topic.id)

        sm.delete_scope(topic.id, cascade=True)
        # Entity should be reassigned to global (NULL scope)
        entity = kg.get_entity('e1')
        assert entity.scope_id is None

    def test_delete_nonexistent_scope(self, sm):
        assert sm.delete_scope('nonexistent') is False


# -- Tree Traversal Tests --


class TestAncestors:
    def test_get_ancestors_deep(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        s1 = sm.create_scope('session', 'S1', parent_id=topic.id)
        s2 = sm.create_scope('session', 'S2', parent_id=s1.id)

        ancestors = sm.get_ancestors(s2.id)
        ancestor_ids = [a.id for a in ancestors]
        assert ancestor_ids == [s1.id, topic.id, project.id]

    def test_get_ancestors_project(self, sm):
        project = sm.create_scope('project', 'P')
        ancestors = sm.get_ancestors(project.id)
        assert ancestors == []

    def test_get_ancestors_topic(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        ancestors = sm.get_ancestors(topic.id)
        assert len(ancestors) == 1
        assert ancestors[0].id == project.id


class TestDescendants:
    def test_get_descendants(self, sm):
        project = sm.create_scope('project', 'P')
        t1 = sm.create_scope('topic', 'T1', parent_id=project.id)
        t2 = sm.create_scope('topic', 'T2', parent_id=project.id)
        s1 = sm.create_scope('session', 'S1', parent_id=t1.id)
        s2 = sm.create_scope('session', 'S2', parent_id=t1.id)
        s3 = sm.create_scope('session', 'S3', parent_id=t2.id)

        descendants = sm.get_descendants(project.id)
        descendant_ids = {d.id for d in descendants}
        assert descendant_ids == {t1.id, t2.id, s1.id, s2.id, s3.id}

    def test_get_descendants_leaf(self, sm):
        project = sm.create_scope('project', 'P')
        descendants = sm.get_descendants(project.id)
        assert descendants == []


class TestChildren:
    def test_get_children(self, sm):
        project = sm.create_scope('project', 'P')
        t1 = sm.create_scope('topic', 'T1', parent_id=project.id)
        t2 = sm.create_scope('topic', 'T2', parent_id=project.id)

        children = sm.get_children(project.id)
        child_ids = {c.id for c in children}
        assert child_ids == {t1.id, t2.id}

    def test_get_children_empty(self, sm):
        project = sm.create_scope('project', 'P')
        assert sm.get_children(project.id) == []


class TestSiblings:
    def test_get_siblings(self, sm):
        project = sm.create_scope('project', 'P')
        t1 = sm.create_scope('topic', 'T1', parent_id=project.id)
        t2 = sm.create_scope('topic', 'T2', parent_id=project.id)
        t3 = sm.create_scope('topic', 'T3', parent_id=project.id)

        siblings = sm.get_siblings(t1.id)
        sibling_ids = {s.id for s in siblings}
        assert sibling_ids == {t2.id, t3.id}
        assert t1.id not in sibling_ids

    def test_get_siblings_only_child(self, sm):
        project = sm.create_scope('project', 'P')
        t1 = sm.create_scope('topic', 'T1', parent_id=project.id)
        assert sm.get_siblings(t1.id) == []

    def test_get_siblings_root_level(self, sm):
        p1 = sm.create_scope('project', 'P1')
        p2 = sm.create_scope('project', 'P2')
        p3 = sm.create_scope('project', 'P3')

        siblings = sm.get_siblings(p1.id)
        sibling_ids = {s.id for s in siblings}
        assert sibling_ids == {p2.id, p3.id}


class TestResolveVisibleScopeIds:
    def test_resolve_session(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        session = sm.create_scope('session', 'S', parent_id=topic.id)

        visible = sm.resolve_visible_scope_ids(session.id)
        # Should be: [session, topic, project, None(global)]
        assert visible[0] == session.id
        assert topic.id in visible
        assert project.id in visible
        assert visible[-1] is None

    def test_resolve_project(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        session = sm.create_scope('session', 'S', parent_id=topic.id)

        visible = sm.resolve_visible_scope_ids(project.id)
        # Project sees: self, descendants (topic, session), global
        assert project.id in visible
        assert topic.id in visible
        assert session.id in visible
        assert visible[-1] is None

    def test_resolve_deep_nesting(self, sm):
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        s1 = sm.create_scope('session', 'S1', parent_id=topic.id)
        s2 = sm.create_scope('session', 'S2', parent_id=s1.id)
        s3 = sm.create_scope('session', 'S3', parent_id=s2.id)

        visible = sm.resolve_visible_scope_ids(s3.id)
        # s3 has no descendants, so: [s3, ...ancestors, None]
        assert s3.id in visible
        assert s2.id in visible
        assert s1.id in visible
        assert topic.id in visible
        assert project.id in visible
        assert visible[-1] is None

    def test_resolve_mid_tree(self, sm):
        """A scope in the middle of the tree sees descendants and ancestors."""
        project = sm.create_scope('project', 'P')
        topic = sm.create_scope('topic', 'T', parent_id=project.id)
        s1 = sm.create_scope('session', 'S1', parent_id=topic.id)
        s2 = sm.create_scope('session', 'S2', parent_id=s1.id)

        visible = sm.resolve_visible_scope_ids(s1.id)
        visible_set = set(id for id in visible if id is not None)
        # s1 sees: self, descendants (s2), ancestors (topic, project), global
        assert s1.id in visible_set
        assert s2.id in visible_set
        assert topic.id in visible_set
        assert project.id in visible_set
        assert None in visible
