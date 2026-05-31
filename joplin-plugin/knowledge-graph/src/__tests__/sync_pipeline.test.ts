/**
 * @jest-environment jsdom
 *
 * Tests for SPEC-JOPLIN-004 — Edit-to-Graph Real-Time Sync
 *
 * Covers:
 * - EntityDiffer: diffing (new, changed, unchanged, removed), dedup, cleanup
 * - SyncPipeline: debounce timing, extraction flow, posting to mnemosyne,
 *   graph-updated events, status changes, force-flush
 * - Status indicator: HTML generation, DOM updates
 * - Scope metadata application from frontmatter
 */

import { EntityDiffer, ExtractedEntity, DiffResult } from '../entity_differ';
import { SyncPipeline, SyncStatus, GraphUpdatedCallback } from '../sync_pipeline';
import { MnemosyneClient, KnowledgeGraphEntity } from '../mnemosyne_client';
import { createStatusIndicatorHtml, updateStatusIndicator } from '../status_indicator';

// ============================================================
// EntityDiffer Tests
// ============================================================
describe('EntityDiffer', () => {
  let differ: EntityDiffer;

  beforeEach(() => {
    differ = new EntityDiffer();
  });

  // --- Dedup Key ---
  describe('dedupKey', () => {
    test('builds key from type:name:scope', () => {
      const entity: ExtractedEntity = {
        type: 'function',
        name: 'parse',
        properties: {},
        scope_id: 'session-1',
      };
      expect(EntityDiffer.dedupKey(entity)).toBe('function:parse:session-1');
    });

    test('uses empty string for missing scope_id', () => {
      const entity: ExtractedEntity = {
        type: 'function',
        name: 'parse',
        properties: {},
      };
      expect(EntityDiffer.dedupKey(entity)).toBe('function:parse:');
    });
  });

  // --- New Entities ---
  describe('new entities', () => {
    test('all entities are new on first diff', () => {
      const entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: { lang: 'python' } },
        { type: 'function', name: 'tokenize', properties: {} },
      ];

      const result = differ.diff('note-1', entities);

      expect(result.added).toHaveLength(2);
      expect(result.removed).toHaveLength(0);
      expect(result.total).toBe(2);
    });

    test('single new entity is detected', () => {
      const first: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      differ.diff('note-1', first);

      const second: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
        { type: 'function', name: 'tokenize', properties: {} },
      ];
      const result = differ.diff('note-1', second);

      expect(result.added).toHaveLength(1);
      expect(result.added[0].name).toBe('tokenize');
      expect(result.removed).toHaveLength(0);
    });
  });

  // --- Unchanged Entities ---
  describe('unchanged entities', () => {
    test('identical entities produce empty diff', () => {
      const entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: { lang: 'python' } },
      ];
      differ.diff('note-1', entities);

      const result = differ.diff('note-1', entities);

      expect(result.added).toHaveLength(0);
      expect(result.removed).toHaveLength(0);
      expect(result.total).toBe(1);
    });
  });

  // --- Changed Entities ---
  describe('changed entities', () => {
    test('entity with different properties is detected as changed', () => {
      const v1: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: { lang: 'python' } },
      ];
      differ.diff('note-1', v1);

      const v2: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: { lang: 'typescript' } },
      ];
      const result = differ.diff('note-1', v2);

      expect(result.added).toHaveLength(1);
      expect(result.added[0].properties.lang).toBe('typescript');
      expect(result.removed).toHaveLength(0);
    });

    test('entity with different source_channel is detected as changed', () => {
      const v1: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {}, source_channel: 'joplin' },
      ];
      differ.diff('note-1', v1);

      const v2: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {}, source_channel: 'code-review' },
      ];
      const result = differ.diff('note-1', v2);

      expect(result.added).toHaveLength(1);
      expect(result.added[0].source_channel).toBe('code-review');
    });
  });

  // --- Removed Entities ---
  describe('removed entities', () => {
    test('entities present before but not now are removed', () => {
      const first: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
        { type: 'function', name: 'tokenize', properties: {} },
      ];
      differ.diff('note-1', first);

      const second: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      const result = differ.diff('note-1', second);

      expect(result.added).toHaveLength(0);
      expect(result.removed).toHaveLength(1);
      expect(result.removed[0]).toBe('function:tokenize:');
    });

    test('all entities removed produces empty total', () => {
      const first: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      differ.diff('note-1', first);

      const result = differ.diff('note-1', []);

      expect(result.added).toHaveLength(0);
      expect(result.removed).toHaveLength(1);
      expect(result.total).toBe(0);
    });
  });

  // --- Deduplication ---
  describe('deduplication', () => {
    test('duplicate entities with same type+name+scope are deduped', () => {
      const entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: { a: 1 } },
        { type: 'function', name: 'parse', properties: { a: 2 } },
      ];

      const result = differ.diff('note-1', entities);

      // Second duplicate should be kept (last-write-wins)
      expect(result.total).toBe(1);
      expect(result.added).toHaveLength(1);
    });
  });

  // --- Per-Note Isolation ---
  describe('per-note isolation', () => {
    test('different notes have independent snapshots', () => {
      const note1Entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      differ.diff('note-1', note1Entities);

      const note2Entities: ExtractedEntity[] = [
        { type: 'class', name: 'Parser', properties: {} },
      ];
      const result2 = differ.diff('note-2', note2Entities);

      // note-2 sees its entities as new (independent of note-1)
      expect(result2.added).toHaveLength(1);
      expect(result2.added[0].name).toBe('Parser');
    });
  });

  // --- Cleanup ---
  describe('cleanup', () => {
    test('clearNote removes snapshot for a note', () => {
      const entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      differ.diff('note-1', entities);
      expect(differ.hasNote('note-1')).toBe(true);

      differ.clearNote('note-1');
      expect(differ.hasNote('note-1')).toBe(false);
    });

    test('getEntityCount returns 0 for cleared note', () => {
      const entities: ExtractedEntity[] = [
        { type: 'function', name: 'parse', properties: {} },
      ];
      differ.diff('note-1', entities);
      expect(differ.getEntityCount('note-1')).toBe(1);

      differ.clearNote('note-1');
      expect(differ.getEntityCount('note-1')).toBe(0);
    });

    test('noteCount tracks active notes', () => {
      expect(differ.noteCount).toBe(0);

      differ.diff('note-1', [{ type: 'function', name: 'a', properties: {} }]);
      expect(differ.noteCount).toBe(1);

      differ.diff('note-2', [{ type: 'function', name: 'b', properties: {} }]);
      expect(differ.noteCount).toBe(2);

      differ.clearNote('note-1');
      expect(differ.noteCount).toBe(1);
    });
  });
});

// ============================================================
// SyncPipeline Tests
// ============================================================
describe('SyncPipeline', () => {
  let pipeline: SyncPipeline;
  let mockClient: MnemosyneClient;
  let mockExtractFn: jest.Mock;
  let mockDetectDomainFn: jest.Mock;
  let mockParseFrontmatterFn: jest.Mock;

  beforeEach(() => {
    // Create a mock MnemosyneClient
    mockClient = new MnemosyneClient('http://127.0.0.1:57832');
    mockClient.createEntities = jest.fn().mockResolvedValue(true);
    mockClient.invalidateCache = jest.fn();

    mockExtractFn = jest.fn().mockReturnValue([]);
    mockDetectDomainFn = jest.fn().mockReturnValue('coding');
    mockParseFrontmatterFn = jest.fn().mockReturnValue(null);

    pipeline = new SyncPipeline({
      client: mockClient,
      extractFn: mockExtractFn,
      detectDomainFn: mockDetectDomainFn,
      parseFrontmatterFn: mockParseFrontmatterFn,
      debounceMs: 100, // Short debounce for tests
    });
  });

  afterEach(() => {
    pipeline.destroy();
  });

  // --- Debounce ---
  describe('debounce timing', () => {
    test('does not process content immediately', () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);

      pipeline.onContentChange('note-1', 'def parse(): pass');
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      // Right after calling onContentChange, nothing should be processed
      expect(graphCb).not.toHaveBeenCalled();
    });

    test('processes content after debounce delay', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', 'def parse(): pass');

      // Wait for debounce (100ms) + processing margin
      await new Promise(resolve => setTimeout(resolve, 200));

      expect(mockExtractFn).toHaveBeenCalledWith('def parse(): pass', 'coding', undefined);
      expect(graphCb).toHaveBeenCalledTimes(1);
    });

    test('coalesces rapid changes into one processing', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      // Three rapid changes
      pipeline.onContentChange('note-1', 'v1');
      pipeline.onContentChange('note-1', 'v2');
      pipeline.onContentChange('note-1', 'v3');

      await new Promise(resolve => setTimeout(resolve, 200));

      // Only one processing with the latest content
      expect(mockExtractFn).toHaveBeenCalledTimes(1);
      expect(mockExtractFn).toHaveBeenCalledWith('v3', 'coding', undefined);
      expect(graphCb).toHaveBeenCalledTimes(1);
    });

    test('forceFlush bypasses debounce', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', 'def parse(): pass');
      pipeline.forceFlush();

      // Should have processed immediately without waiting
      expect(mockExtractFn).toHaveBeenCalledWith('def parse(): pass', 'coding', undefined);
      expect(graphCb).toHaveBeenCalledTimes(1);
    });
  });

  // --- Entity Diffing Integration ---
  describe('entity diffing', () => {
    test('only posts new entities to mnemosyne', async () => {
      pipeline.setMnemosyneAvailable(true);
      mockExtractFn
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: {} },
          { type: 'function', name: 'tokenize', properties: {} },
        ])
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: {} },
          { type: 'function', name: 'tokenize', properties: {} },
          { type: 'class', name: 'Parser', properties: {} },
        ]);

      // First extraction — all entities are new
      pipeline.onContentChange('note-1', 'content-v1');
      pipeline.forceFlush();

      expect(mockClient.createEntities).toHaveBeenCalledTimes(1);
      const firstCallEntities = (mockClient.createEntities as jest.Mock).mock.calls[0][0];
      expect(firstCallEntities).toHaveLength(2);

      // Second extraction — only new class entity is posted
      (mockClient.createEntities as jest.Mock).mockClear();
      pipeline.onContentChange('note-1', 'content-v2');
      pipeline.forceFlush();

      expect(mockClient.createEntities).toHaveBeenCalledTimes(1);
      const secondCallEntities = (mockClient.createEntities as jest.Mock).mock.calls[0][0];
      expect(secondCallEntities).toHaveLength(1);
      expect(secondCallEntities[0].name).toBe('Parser');
    });

    test('does not post unchanged entities', async () => {
      pipeline.setMnemosyneAvailable(true);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: { lang: 'python' } },
      ]);

      // First call — posts the entity
      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();
      expect(mockClient.createEntities).toHaveBeenCalledTimes(1);

      // Second call with same content — no changes, no post
      (mockClient.createEntities as jest.Mock).mockClear();
      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();
      expect(mockClient.createEntities).not.toHaveBeenCalled();
    });

    test('posts changed entities with updated properties', async () => {
      pipeline.setMnemosyneAvailable(true);
      mockExtractFn
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: { version: 1 } },
        ])
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: { version: 2 } },
        ]);

      pipeline.onContentChange('note-1', 'v1');
      pipeline.forceFlush();
      expect(mockClient.createEntities).toHaveBeenCalledTimes(1);

      (mockClient.createEntities as jest.Mock).mockClear();
      pipeline.onContentChange('note-1', 'v2');
      pipeline.forceFlush();

      expect(mockClient.createEntities).toHaveBeenCalledTimes(1);
      const posted = (mockClient.createEntities as jest.Mock).mock.calls[0][0];
      expect(posted[0].properties.version).toBe(2);
    });
  });

  // --- Scope Metadata ---
  describe('scope metadata from frontmatter', () => {
    test('passes parsed frontmatter to extraction function', async () => {
      const metadata = { session_id: 's-1', project: 'my-proj', channel: 'code-review' };
      mockParseFrontmatterFn.mockReturnValue(metadata);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', '---\nsession_id: s-1\n---\ndef parse(): pass');
      pipeline.forceFlush();

      expect(mockParseFrontmatterFn).toHaveBeenCalledWith('---\nsession_id: s-1\n---\ndef parse(): pass');
      expect(mockExtractFn).toHaveBeenCalledWith(
        '---\nsession_id: s-1\n---\ndef parse(): pass',
        'coding',
        metadata,
      );
    });

    test('passes undefined when no frontmatter', async () => {
      mockParseFrontmatterFn.mockReturnValue(null);
      mockExtractFn.mockReturnValue([]);

      pipeline.onContentChange('note-1', 'no frontmatter here');
      pipeline.forceFlush();

      expect(mockExtractFn).toHaveBeenCalledWith('no frontmatter here', 'coding', undefined);
    });
  });

  // --- Graph Updated Events ---
  describe('graph-updated events', () => {
    test('emits graph-updated with entity list and diff', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: { lang: 'ts' } },
      ]);

      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();

      expect(graphCb).toHaveBeenCalledTimes(1);
      const call = graphCb.mock.calls[0][0];
      expect(call.noteId).toBe('note-1');
      expect(call.diff.added).toHaveLength(1);
      expect(call.diff.total).toBe(1);
      expect(call.entities).toHaveLength(1);
      expect(call.entities[0].name).toBe('parse');
    });

    test('does not emit when nothing changed', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      // First call — emits
      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();
      expect(graphCb).toHaveBeenCalledTimes(1);

      // Second identical call — no emit
      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();
      expect(graphCb).toHaveBeenCalledTimes(1);
    });

    test('includes all entities in event after multiple changes', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: {} },
        ])
        .mockReturnValueOnce([
          { type: 'function', name: 'parse', properties: {} },
          { type: 'function', name: 'tokenize', properties: {} },
        ]);

      pipeline.onContentChange('note-1', 'v1');
      pipeline.forceFlush();

      pipeline.onContentChange('note-1', 'v2');
      pipeline.forceFlush();

      // Second call should include both entities
      const secondCall = graphCb.mock.calls[1][0];
      expect(secondCall.entities).toHaveLength(2);
    });
  });

  // --- Status Changes ---
  describe('status changes', () => {
    test('emits connected status when setMnemosyneAvailable(true)', () => {
      const statusCb = jest.fn();
      pipeline.onStatusChange(statusCb);

      pipeline.setMnemosyneAvailable(true);

      expect(statusCb).toHaveBeenCalledWith('connected');
    });

    test('emits unavailable status when setMnemosyneAvailable(false)', () => {
      const statusCb = jest.fn();
      pipeline.onStatusChange(statusCb);

      pipeline.setMnemosyneAvailable(false);

      expect(statusCb).toHaveBeenCalledWith('unavailable');
    });

    test('emits syncing status during entity post', async () => {
      const statusCb = jest.fn();
      pipeline.onStatusChange(statusCb);
      pipeline.setMnemosyneAvailable(true);
      statusCb.mockClear();

      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();

      // Should have transitioned: syncing -> connected
      const statuses = statusCb.mock.calls.map((c: any[]) => c[0]);
      expect(statuses).toContain('syncing');
      expect(statuses[statuses.length - 1]).toBe('connected');
    });

    test('emits unavailable when mnemosyne post fails', async () => {
      const statusCb = jest.fn();
      pipeline.onStatusChange(statusCb);
      pipeline.setMnemosyneAvailable(true);
      statusCb.mockClear();

      (mockClient.createEntities as jest.Mock).mockRejectedValue(new Error('ECONNREFUSED'));

      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();

      // Allow async to settle
      await new Promise(resolve => setTimeout(resolve, 50));

      const statuses = statusCb.mock.calls.map((c: any[]) => c[0]);
      expect(statuses).toContain('unavailable');
    });
  });

  // --- Note Close ---
  describe('note close', () => {
    test('clears differ state on note close', async () => {
      mockExtractFn.mockReturnValue([
        { type: 'function', name: 'parse', properties: {} },
      ]);

      pipeline.onContentChange('note-1', 'content');
      await pipeline.forceFlush();

      expect(pipeline.getEntityCount('note-1')).toBe(1);

      pipeline.onNoteClose('note-1');
      expect(pipeline.getEntityCount('note-1')).toBe(0);
    });
  });

  // --- Destroy ---
  describe('destroy', () => {
    test('cancels pending debounce timer', () => {
      mockExtractFn.mockReturnValue([]);

      pipeline.onContentChange('note-1', 'content');
      pipeline.destroy();

      // After destroy, the timer should be cleared
      // Verify by checking that extractFn is not called after debounce period
      const extractCalls = mockExtractFn.mock.calls.length;
      return new Promise<void>((resolve) => {
        setTimeout(() => {
          expect(mockExtractFn.mock.calls.length).toBe(extractCalls);
          resolve();
        }, 200);
      });
    });
  });

  // --- No entities extracted ---
  describe('empty extraction', () => {
    test('no-op when extractFn returns empty', async () => {
      const graphCb = jest.fn();
      pipeline.onGraphUpdated(graphCb);
      mockExtractFn.mockReturnValue([]);

      pipeline.onContentChange('note-1', 'no entities here');
      pipeline.forceFlush();

      // No entities means no diff, no event
      expect(graphCb).not.toHaveBeenCalled();
      expect(mockClient.createEntities).not.toHaveBeenCalled();
    });
  });
});

// ============================================================
// Status Indicator Tests
// ============================================================
describe('Status Indicator', () => {
  describe('createStatusIndicatorHtml', () => {
    test('generates HTML with green dot for connected', () => {
      const html = createStatusIndicatorHtml('connected', 5);
      expect(html).toContain('#4CAF50');
      expect(html).toContain('mnemosyne connected');
      expect(html).toContain('5 entities');
    });

    test('generates HTML with yellow dot for syncing', () => {
      const html = createStatusIndicatorHtml('syncing', 3);
      expect(html).toContain('#FFC107');
      expect(html).toContain('syncing...');
      expect(html).toContain('3 entities');
    });

    test('generates HTML with red dot for unavailable', () => {
      const html = createStatusIndicatorHtml('unavailable', 0);
      expect(html).toContain('#F44336');
      expect(html).toContain('mnemosyne unavailable');
      expect(html).toContain('0 entities');
    });
  });

  describe('updateStatusIndicator', () => {
    let container: HTMLDivElement;

    beforeEach(() => {
      container = document.createElement('div');
      // Build DOM programmatically instead of using innerHTML
      const wrapper = document.createElement('div');
      wrapper.id = 'kg-sync-status';

      const dot = document.createElement('span');
      dot.id = 'kg-sync-dot';
      dot.style.background = '#F44336';
      wrapper.appendChild(dot);

      const label = document.createElement('span');
      label.id = 'kg-sync-label';
      label.textContent = 'mnemosyne unavailable';
      wrapper.appendChild(label);

      const badge = document.createElement('span');
      badge.id = 'kg-entity-count';
      badge.textContent = '0 entities';
      wrapper.appendChild(badge);

      container.appendChild(wrapper);
    });

    test('updates dot color to green', () => {
      updateStatusIndicator(container, 'connected', 10);

      const dot = container.querySelector('#kg-sync-dot') as HTMLElement;
      expect(dot?.style.background).toBe('rgb(76, 175, 80)'); // #4CAF50 in rgb
    });

    test('updates label text', () => {
      updateStatusIndicator(container, 'syncing', 5);

      const label = container.querySelector('#kg-sync-label');
      expect(label?.textContent).toBe('syncing...');
    });

    test('updates entity count', () => {
      updateStatusIndicator(container, 'connected', 42);

      const count = container.querySelector('#kg-entity-count');
      expect(count?.textContent).toBe('42 entities');
    });
  });
});
