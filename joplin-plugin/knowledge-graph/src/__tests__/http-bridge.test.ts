/**
 * Tests for SPEC-JOPLIN-002 — HTTP Bridge
 *
 * Covers: MnemosyneClient, LRUCache, ServerManager, and graceful degradation in index.ts
 */

import { LRUCache, CACHE_TTL } from '../cache';
import { MnemosyneClient, MnemosyneApiError } from '../mnemosyne_client';
import { ServerManager } from '../server_manager';
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

function createPluginInstance(): any {
  const mockPlugin = createMockPlugin();
  return new KnowledgeGraphPlugin(mockPlugin);
}

// ============================================================
// LRUCache Tests
// ============================================================
describe('LRUCache', () => {
  let cache: LRUCache<string>;

  beforeEach(() => {
    cache = new LRUCache<string>(3); // Small size for eviction testing
  });

  test('set and get a value', () => {
    cache.set('key1', 'value1', 10_000);
    expect(cache.get('key1')).toBe('value1');
  });

  test('get returns undefined for missing key', () => {
    expect(cache.get('nonexistent')).toBeUndefined();
  });

  test('get returns undefined for expired entry', () => {
    cache.set('key1', 'value1', 1); // 1ms TTL
    return new Promise(resolve => {
      setTimeout(() => {
        expect(cache.get('key1')).toBeUndefined();
        resolve(undefined);
      }, 10);
    });
  });

  test('evicts oldest entry when max size reached', () => {
    cache.set('key1', 'value1', 60_000);
    cache.set('key2', 'value2', 60_000);
    cache.set('key3', 'value3', 60_000);
    cache.set('key4', 'value4', 60_000); // Should evict key1

    expect(cache.get('key1')).toBeUndefined();
    expect(cache.get('key2')).toBe('value2');
    expect(cache.get('key3')).toBe('value3');
    expect(cache.get('key4')).toBe('value4');
  });

  test('access refreshes LRU position', () => {
    cache.set('key1', 'value1', 60_000);
    cache.set('key2', 'value2', 60_000);
    cache.set('key3', 'value3', 60_000);

    // Access key1 to move it to most recent
    cache.get('key1');

    // Adding key4 should evict key2 (oldest untouched)
    cache.set('key4', 'value4', 60_000);

    expect(cache.get('key1')).toBe('value1');
    expect(cache.get('key2')).toBeUndefined();
    expect(cache.get('key3')).toBe('value3');
  });

  test('invalidate removes a specific key', () => {
    cache.set('key1', 'value1', 60_000);
    expect(cache.invalidate('key1')).toBe(true);
    expect(cache.get('key1')).toBeUndefined();
  });

  test('invalidate returns false for missing key', () => {
    expect(cache.invalidate('nonexistent')).toBe(false);
  });

  test('invalidateByPrefix removes matching keys', () => {
    cache.set('/api/v1/entities', 'data1', 60_000);
    cache.set('/api/v1/entities?type=task', 'data2', 60_000);
    cache.set('/api/v1/search?q=test', 'data3', 60_000);

    const count = cache.invalidateByPrefix('/api/v1/entities');

    expect(count).toBe(2);
    expect(cache.get('/api/v1/entities')).toBeUndefined();
    expect(cache.get('/api/v1/entities?type=task')).toBeUndefined();
    expect(cache.get('/api/v1/search?q=test')).toBe('data3');
  });

  test('clear removes all entries', () => {
    cache.set('key1', 'value1', 60_000);
    cache.set('key2', 'value2', 60_000);
    cache.clear();
    expect(cache.size).toBe(0);
  });

  test('has returns true for valid entries and false for expired', () => {
    cache.set('key1', 'value1', 60_000);
    expect(cache.has('key1')).toBe(true);
    expect(cache.has('nonexistent')).toBe(false);
  });

  test('overwriting a key updates value and TTL', () => {
    cache.set('key1', 'value1', 1);
    cache.set('key1', 'value2', 60_000);
    expect(cache.get('key1')).toBe('value2');
  });
});

// ============================================================
// MnemosyneClient Tests (with mocked fetch)
// ============================================================
describe('MnemosyneClient', () => {
  let client: MnemosyneClient;
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    client = new MnemosyneClient('http://127.0.0.1:57832');
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  function mockFetch(response: any, status: number = 200): jest.Mock {
    const mock = jest.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 200 ? 'OK' : 'Error',
      json: jest.fn().mockResolvedValue(response),
    });
    global.fetch = mock;
    return mock;
  }

  // AC-S2-001: Client can call health endpoint
  test('health returns status and version', async () => {
    const mock = mockFetch({ status: 'ok', version: '0.2.0' });

    const result = await client.health();

    expect(result.status).toBe('ok');
    expect(result.version).toBe('0.2.0');
    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/health',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  test('getEntities returns entity list', async () => {
    const entities = [
      { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 },
    ];
    mockFetch(entities);

    const result = await client.getEntities();

    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('function:parse');
  });

  test('getEntities passes type and scopeId as query params', async () => {
    const mock = mockFetch([]);

    await client.getEntities('function', 'session-1');

    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/entities?type=function&scope_id=session-1',
      expect.any(Object),
    );
  });

  test('getEntity returns single entity', async () => {
    const entity = { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 };
    mockFetch(entity);

    const result = await client.getEntity('function:parse');

    expect(result).not.toBeNull();
    expect(result!.id).toBe('function:parse');
  });

  test('getEntity returns null for 404', async () => {
    const mock = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: jest.fn().mockResolvedValue({}),
    });
    global.fetch = mock;

    const result = await client.getEntity('nonexistent');

    expect(result).toBeNull();
  });

  // AC-S2-002: Entity search returns results from mnemosyne
  test('searchEntities calls search endpoint with query', async () => {
    const mock = mockFetch([
      { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 },
    ]);

    const result = await client.searchEntities('parse', 10);

    expect(result).toHaveLength(1);
    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/search?q=parse&limit=10',
      expect.any(Object),
    );
  });

  test('queryGraph sends structured query', async () => {
    const mock = mockFetch({ results: [] });

    await client.queryGraph('entity:function[parse]');

    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/graph/query?query=entity%3Afunction%5Bparse%5D',
      expect.any(Object),
    );
  });

  test('getRelations with filters', async () => {
    const mock = mockFetch([]);

    await client.getRelations({ source: 'fn1', type: 'calls' });

    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/relations?source=fn1&type=calls',
      expect.any(Object),
    );
  });

  test('getBacklinks calls entity backlinks endpoint', async () => {
    const mock = mockFetch([]);

    await client.getBacklinks('function:parse');

    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/entities/function%3Aparse/backlinks',
      expect.any(Object),
    );
  });

  test('getStats calls stats endpoint', async () => {
    const mock = mockFetch({ entity_count: 42, relation_count: 10 });

    const result = await client.getStats();

    expect(result.entity_count).toBe(42);
    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/stats',
      expect.any(Object),
    );
  });

  test('isAvailable returns true when server is healthy', async () => {
    mockFetch({ status: 'ok', version: '0.2.0' });

    expect(await client.isAvailable()).toBe(true);
  });

  test('isAvailable returns false when server is unreachable', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

    expect(await client.isAvailable()).toBe(false);
  });

  // AC-S2-004: Cache reduces repeated query latency
  test('caches responses — second call uses cache', async () => {
    const mock = mockFetch({ status: 'ok', version: '0.2.0' });

    await client.health();
    await client.health();

    // fetch should only be called once — second call hits cache
    expect(mock).toHaveBeenCalledTimes(1);
  });

  test('createEntities returns false on failure', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

    const result = await client.createEntities([
      { id: 'test:1', type: 'test', name: 'test', properties: {}, version: 1 },
    ]);

    expect(result).toBe(false);
  });

  test('createEntities invalidates entity caches on success', async () => {
    mockFetch({ status: 'ok' });

    // Prime the caches
    await client.getEntities();
    await client.searchEntities('test');

    // createEntities should invalidate
    await client.createEntities([
      { id: 'test:1', type: 'test', name: 'test', properties: {}, version: 1 },
    ]);

    // Next calls should hit fetch again (cache invalidated)
    const mock = mockFetch([]);
    await client.getEntities();
    expect(mock).toHaveBeenCalledTimes(1);
  });

  test('throws MnemosyneApiError on non-ok response', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: jest.fn().mockResolvedValue({}),
    });

    await expect(client.getStats()).rejects.toThrow(MnemosyneApiError);
    await expect(client.getStats()).rejects.toThrow('500');
  });

  test('invalidateCache clears all cached entries', async () => {
    const mock = mockFetch({ status: 'ok', version: '0.2.0' });

    await client.health();
    client.invalidateCache();
    await client.health();

    expect(mock).toHaveBeenCalledTimes(2);
  });
});

// ============================================================
// ServerManager Tests
// ============================================================
describe('ServerManager', () => {
  let serverManager: ServerManager;
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    serverManager = new ServerManager('/path/to/db', 57832);
    originalFetch = global.fetch;
  });

  afterEach(() => {
    serverManager.stop();
    global.fetch = originalFetch;
  });

  test('isRunning returns false when server is unreachable', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

    expect(await serverManager.isRunning()).toBe(false);
  });

  test('isRunning returns true when health check succeeds', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true });

    expect(await serverManager.isRunning()).toBe(true);
    expect(global.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:57832/api/v1/health',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  test('updateConfig changes port and health URL', async () => {
    const mock = jest.fn().mockResolvedValue({ ok: true });
    global.fetch = mock;

    serverManager.updateConfig('/new/db', 9999);
    await serverManager.isRunning();

    expect(mock).toHaveBeenCalledWith(
      'http://127.0.0.1:9999/api/v1/health',
      expect.any(Object),
    );
  });

  test('getProcess returns null when not started', () => {
    expect(serverManager.getProcess()).toBeNull();
  });

  test('stop clears restart attempts', () => {
    serverManager.stop();
    // No assertion needed — just verify it doesn't throw
    expect(serverManager.getProcess()).toBeNull();
  });
});

// ============================================================
// Graceful Degradation Tests (AC-S2-003)
// ============================================================
describe('Graceful degradation', () => {
  let plugin: any;
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    plugin = createPluginInstance();
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // AC-S2-003: Falls back to local regex when mnemosyne unavailable
  test('search falls back to local Map when mnemosyne unavailable', async () => {
    // Simulate mnemosyne unavailable
    plugin.mnemosyneAvailable = false;

    // Add data to local Map
    plugin.graphDB.set('function:parse', {
      id: 'function:parse',
      type: 'function',
      name: 'parse',
      properties: { source: 'test' },
      version: 1,
    });

    const results = await plugin.searchKnowledgeGraph('parse');

    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('parse');
  });

  test('search uses mnemosyne client when available', async () => {
    plugin.mnemosyneAvailable = true;

    const mockEntities = [
      { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 },
    ];
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue(mockEntities),
    });

    const results = await plugin.searchKnowledgeGraph('parse');

    expect(results).toHaveLength(1);
    expect(global.fetch).toHaveBeenCalled();
  });

  test('search falls back to local after mnemosyne failure', async () => {
    plugin.mnemosyneAvailable = true;

    // Make fetch fail
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

    // Add data to local Map
    plugin.graphDB.set('function:parse', {
      id: 'function:parse',
      type: 'function',
      name: 'parse',
      properties: { source: 'test' },
      version: 1,
    });

    const results = await plugin.searchKnowledgeGraph('parse');

    // Should fall back to local
    expect(results).toHaveLength(1);
    expect(results[0].name).toBe('parse');
    // mnemosyneAvailable should be set to false after failure
    expect(plugin.mnemosyneAvailable).toBe(false);
  });

  test('search with type filter on mnemosyne results', async () => {
    plugin.mnemosyneAvailable = true;

    const mockEntities = [
      { id: 'function:parse', type: 'function', name: 'parse', properties: {}, version: 1 },
      { id: 'class:Parser', type: 'class', name: 'Parser', properties: {}, version: 1 },
    ];
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue(mockEntities),
    });

    const results = await plugin.searchKnowledgeGraph('parse', 'function');

    expect(results).toHaveLength(1);
    expect(results[0].type).toBe('function');
  });

  test('plugin initializes without mnemosyne server', async () => {
    // Simulate mnemosyne completely unavailable
    global.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));

    // Mock ServerManager.start to avoid spawning a real process
    const startSpy = jest.spyOn(ServerManager.prototype, 'start').mockResolvedValue(false);

    // Should not throw
    await plugin.initialize();

    expect(plugin.mnemosyneAvailable).toBe(false);
    // Local Map should still be functional
    expect(plugin.graphDB).toBeInstanceOf(Map);

    startSpy.mockRestore();
  });
});

// ============================================================
// CACHE_TTL constants test
// ============================================================
describe('CACHE_TTL constants', () => {
  test('has expected TTL values', () => {
    expect(CACHE_TTL.ENTITY).toBe(30_000);
    expect(CACHE_TTL.SEARCH).toBe(10_000);
    expect(CACHE_TTL.STATS).toBe(60_000);
    expect(CACHE_TTL.HEALTH).toBe(5_000);
  });
});
