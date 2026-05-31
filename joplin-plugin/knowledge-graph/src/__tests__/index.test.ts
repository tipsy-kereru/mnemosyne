/**
 * TDD Tests for SPEC-SESSION-002 (T4-T6)
 *
 * Session/scope support for the Joplin Knowledge Graph Plugin.
 *
 * RED phase: All tests written before implementation.
 */

import KnowledgeGraphPlugin from '../index';

// Helper: create a mock plugin object
function createMockPlugin() {
  return {
    settings: {
      get: jest.fn().mockResolvedValue(null),
      set: jest.fn().mockResolvedValue(undefined),
    },
    registry: {
      register: jest.fn().mockResolvedValue(undefined),
    },
    onNoteSave: jest.fn(),
    onCalculateSyntaxHighlight: jest.fn(),
    onMessage: jest.fn(),
    dialogs: {
      create: jest.fn(),
      showMessage: jest.fn().mockResolvedValue(undefined),
    },
    views: {
      createPanel: jest.fn(),
    },
    currentNote: jest.fn().mockResolvedValue(null),
  };
}

// Helper: create plugin instance (use any to bypass private access)
function createPluginInstance(): any {
  const mockPlugin = createMockPlugin();
  return new KnowledgeGraphPlugin(mockPlugin);
}

// ============================================================
// T4: parseFrontmatter Tests
// ============================================================
describe('parseFrontmatter', () => {
  let plugin: any;

  beforeEach(() => {
    plugin = createPluginInstance();
  });

  test('test_parseFrontmatter_with_valid_frontmatter', () => {
    const content = `---
session_id: abc-123
project: my-project
topic: auth-refactor
channel: code-review
---
# Note Title
Some content here.`;

    const result = plugin.parseFrontmatter(content);

    expect(result).not.toBeNull();
    expect(result.session_id).toBe('abc-123');
    expect(result.project).toBe('my-project');
    expect(result.topic).toBe('auth-refactor');
    expect(result.channel).toBe('code-review');
  });

  test('test_parseFrontmatter_with_no_frontmatter', () => {
    const content = `# Note Title
Some content here.
No frontmatter at all.`;

    const result = plugin.parseFrontmatter(content);

    expect(result).toBeNull();
  });

  test('test_parseFrontmatter_with_partial_fields', () => {
    const content = `---
session_id: abc-123
project: my-project
---
Content after frontmatter.`;

    const result = plugin.parseFrontmatter(content);

    expect(result).not.toBeNull();
    expect(result.session_id).toBe('abc-123');
    expect(result.project).toBe('my-project');
    expect(result.topic).toBeUndefined();
    expect(result.channel).toBeUndefined();
  });

  test('test_parseFrontmatter_with_unclosed_delimiter (EC-001)', () => {
    const content = `---
session_id: abc-123
project: my-project
This line has no closing delimiter`;

    const result = plugin.parseFrontmatter(content);

    // Unclosed --- means no valid frontmatter
    expect(result).toBeNull();
  });

  test('test_parseFrontmatter_with_empty_frontmatter (EC-001)', () => {
    const content = `---
---
Content after empty frontmatter.`;

    const result = plugin.parseFrontmatter(content);

    // Empty frontmatter returns null
    expect(result).toBeNull();
  });

  test('test_parseFrontmatter_with_invalid_lines (EC-001)', () => {
    const content = `---
session_id: abc-123
this line has no colon
  : value_without_key
project: my-project
another invalid line
---
Content here.`;

    const result = plugin.parseFrontmatter(content);

    // Should parse valid lines and ignore invalid ones
    expect(result).not.toBeNull();
    expect(result.session_id).toBe('abc-123');
    expect(result.project).toBe('my-project');
  });

  test('test_parseFrontmatter_sets_channel_default', () => {
    const content = `---
session_id: abc-123
---
Content here.`;

    const result = plugin.parseFrontmatter(content);

    expect(result).not.toBeNull();
    expect(result.session_id).toBe('abc-123');
    // channel is not specified, should be undefined (not defaulted to 'joplin')
    expect(result.channel).toBeUndefined();
  });
});

// ============================================================
// T4: extractBasedOnDomain with scope metadata
// ============================================================
describe('extractBasedOnDomain with scope', () => {
  let plugin: any;

  beforeEach(() => {
    plugin = createPluginInstance();
  });

  test('test_extract_with_session_metadata', () => {
    const content = `def parse_config(): pass`;
    const metadata = {
      session_id: 's-1',
      project: 'my-project',
      channel: 'code-review',
    };

    const entities = plugin.extractBasedOnDomain(content, 'coding', metadata);

    expect(entities.length).toBeGreaterThan(0);
    for (const entity of entities) {
      expect(entity.scope_id).toBe('s-1');
      expect(entity.source_channel).toBe('code-review');
    }
  });

  test('test_extract_without_session_metadata', () => {
    const content = `def parse_config(): pass`;

    const entities = plugin.extractBasedOnDomain(content, 'coding');

    for (const entity of entities) {
      expect(entity.scope_id).toBeUndefined();
      expect(entity.source_channel).toBeUndefined();
    }
  });

  test('test_extract_scope_priority', () => {
    const content = `def parse_config(): pass`;

    // session_id takes priority over project
    const metadata1 = {
      session_id: 's-1',
      project: 'my-project',
    };
    const entities1 = plugin.extractBasedOnDomain(content, 'coding', metadata1);
    for (const entity of entities1) {
      expect(entity.scope_id).toBe('s-1');
    }

    // project is used when no session_id
    const metadata2 = {
      project: 'my-project',
    };
    const entities2 = plugin.extractBasedOnDomain(content, 'coding', metadata2);
    for (const entity of entities2) {
      expect(entity.scope_id).toBe('my-project');
    }

    // topic is used when no session_id or project
    const metadata3 = {
      topic: 'auth-topic',
    };
    const entities3 = plugin.extractBasedOnDomain(content, 'coding', metadata3);
    for (const entity of entities3) {
      expect(entity.scope_id).toBe('auth-topic');
    }
  });
});

// ============================================================
// T5: processWikiLinks with scope modifiers
// ============================================================
describe('processWikiLinks with scope', () => {
  let plugin: any;

  beforeEach(() => {
    plugin = createPluginInstance();
  });

  test('test_wiki_link_with_session_modifier', () => {
    const text = `Some text [[entity:function:parse@session:my-session]] more text`;

    const result = plugin.processWikiLinks(text);

    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).toContain('data-scope-session="my-session"');
    expect(result).toContain('entity:function:parse');
  });

  test('test_wiki_link_with_multiple_modifiers', () => {
    const text = `Check [[entity:function:parse@session:s1@channel:code]] here`;

    const result = plugin.processWikiLinks(text);

    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).toContain('data-scope-session="s1"');
    expect(result).toContain('data-scope-channel="code"');
  });

  test('test_wiki_link_without_modifiers', () => {
    const text = `Check [[entity:function:parse]] here`;

    const result = plugin.processWikiLinks(text);

    // Should render unchanged from current behavior
    expect(result).toBe(
      'Check <span class="kg-entity-link" data-entity="entity:function:parse">entity:function:parse</span> here'
    );
    // Should NOT contain any data-scope attributes
    expect(result).not.toContain('data-scope-session');
    expect(result).not.toContain('data-scope-project');
    expect(result).not.toContain('data-scope-channel');
  });

  test('test_wiki_link_with_unknown_modifier (EC-002)', () => {
    const text = `Check [[entity:function:parse@unknown:value]] here`;

    const result = plugin.processWikiLinks(text);

    // Unknown modifier is silently ignored
    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).not.toContain('data-scope-unknown');
    // No error or crash
    expect(result).not.toContain('@unknown');
  });

  test('test_wiki_link_with_empty_modifier_value (EC-002)', () => {
    const text = `Check [[entity:function:parse@session:]] here`;

    const result = plugin.processWikiLinks(text);

    // @session: without value is ignored
    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).not.toContain('data-scope-session');
  });

  test('test_wiki_link_with_at_in_entity_name (EC-002)', () => {
    // @ in entity name that is not a known modifier prefix should be preserved
    const text = `Check [[entity:function:parse@other]] here`;

    const result = plugin.processWikiLinks(text);

    // @other without a known prefix (session:/project:/channel:) is not a modifier
    // The entity path should be preserved as-is
    expect(result).toContain('data-entity="entity:function:parse@other"');
  });

  test('test_wiki_link_with_project_modifier', () => {
    const text = `See [[entity:function:parse@project:my-proj]] ref`;

    const result = plugin.processWikiLinks(text);

    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).toContain('data-scope-project="my-proj"');
  });

  test('test_wiki_link_with_channel_modifier', () => {
    const text = `See [[entity:function:parse@channel:email]] ref`;

    const result = plugin.processWikiLinks(text);

    expect(result).toContain('data-entity="entity:function:parse"');
    expect(result).toContain('data-scope-channel="email"');
  });
});

// ============================================================
// T6: Scope Persistence
// ============================================================
describe('Scope persistence', () => {
  let plugin: any;
  let mockPlugin: ReturnType<typeof createMockPlugin>;

  beforeEach(() => {
    mockPlugin = createMockPlugin();
    plugin = new KnowledgeGraphPlugin(mockPlugin);
  });

  test('test_save_and_load_scopes', async () => {
    // Add some scopes to the scopeIndex
    plugin.scopeIndex = new Map([
      ['project:my-project', {
        id: 'project:my-project',
        name: 'my-project',
        scope_type: 'project',
        parent_id: undefined,
      }],
      ['session:s-1', {
        id: 'session:s-1',
        name: 's-1',
        scope_type: 'session',
        parent_id: 'project:my-project',
      }],
    ]);

    // Save
    await plugin.saveKnowledgeGraph();

    // Verify settings.set was called
    expect(mockPlugin.settings.set).toHaveBeenCalledTimes(1);
    const savedJson = mockPlugin.settings.set.mock.calls[0][1];
    const savedData = JSON.parse(savedJson);

    // Verify scopes are in saved data
    expect(savedData.scopes).toBeDefined();
    expect(savedData.scopes).toHaveLength(2);
    expect(savedData.scopes[0].id).toBe('project:my-project');
    expect(savedData.scopes[1].id).toBe('session:s-1');
    expect(savedData.scopes[1].parent_id).toBe('project:my-project');

    // Simulate loading: reset plugin state and configure mock to return saved data
    plugin.scopeIndex = new Map();
    plugin.graphDB = new Map();
    plugin.relationIndex = new Map();

    mockPlugin.settings.get.mockResolvedValue(savedJson);

    // Load
    await plugin.loadKnowledgeGraph();

    const loadedScopes = plugin.scopeIndex;
    expect(loadedScopes.size).toBe(2);
    expect(loadedScopes.get('project:my-project').name).toBe('my-project');
    expect(loadedScopes.get('project:my-project').scope_type).toBe('project');
    expect(loadedScopes.get('session:s-1').name).toBe('s-1');
    expect(loadedScopes.get('session:s-1').scope_type).toBe('session');
  });

  test('test_load_legacy_data_without_scopes', async () => {
    // Legacy data without scopes field
    const legacyData = JSON.stringify({
      entities: [
        { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 },
      ],
      relations: [],
    });

    mockPlugin.settings.get.mockResolvedValue(legacyData);

    await plugin.loadKnowledgeGraph();

    const loadedScopes = plugin.scopeIndex;
    // Legacy data initializes empty scopeIndex
    expect(loadedScopes.size).toBe(0);
    // Entities are still loaded normally
    expect(plugin.graphDB.size).toBe(1);
  });

  test('test_scope_hierarchy_preserved', async () => {
    // Create a hierarchy: project -> topic -> session
    plugin.scopeIndex = new Map([
      ['project:p1', {
        id: 'project:p1',
        name: 'p1',
        scope_type: 'project',
      }],
      ['topic:t1', {
        id: 'topic:t1',
        name: 't1',
        scope_type: 'topic',
        parent_id: 'project:p1',
      }],
      ['session:s1', {
        id: 'session:s1',
        name: 's1',
        scope_type: 'session',
        parent_id: 'topic:t1',
      }],
    ]);

    await plugin.saveKnowledgeGraph();

    const savedJson = mockPlugin.settings.set.mock.calls[0][1];
    const savedData = JSON.parse(savedJson);

    // Verify hierarchy preserved in saved data
    expect(savedData.scopes).toHaveLength(3);
    const topicScope = savedData.scopes.find((s: any) => s.id === 'topic:t1');
    expect(topicScope.parent_id).toBe('project:p1');
    const sessionScope = savedData.scopes.find((s: any) => s.id === 'session:s1');
    expect(sessionScope.parent_id).toBe('topic:t1');

    // Load back and verify
    plugin.scopeIndex = new Map();
    mockPlugin.settings.get.mockResolvedValue(savedJson);

    await plugin.loadKnowledgeGraph();

    const loaded = plugin.scopeIndex;
    expect(loaded.get('topic:t1').parent_id).toBe('project:p1');
    expect(loaded.get('session:s1').parent_id).toBe('topic:t1');
    // Root scope has no parent
    expect(loaded.get('project:p1').parent_id).toBeUndefined();
  });
});
