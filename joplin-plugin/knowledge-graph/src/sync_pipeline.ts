/*
 * Sync Pipeline for SPEC-JOPLIN-004
 *
 * Debounced content change handler that:
 * - Takes note content and runs regex extraction
 * - Diffs against previous extraction for same note
 * - Posts new/changed entities to mnemosyne
 * - Emits graph-updated event for graph view
 * - Supports force-flush on explicit save (bypass debounce)
 */

import { MnemosyneClient, KnowledgeGraphEntity } from './mnemosyne_client';
import { EntityDiffer, ExtractedEntity, DiffResult } from './entity_differ';

// Callback types
export type GraphUpdatedCallback = (data: {
  entities: KnowledgeGraphEntity[];
  diff: DiffResult;
  noteId: string;
}) => void;

export type StatusChangeCallback = (status: SyncStatus) => void;

export type SyncStatus = 'connected' | 'syncing' | 'unavailable';

// Extraction function type — matches KnowledgeGraphPlugin.extractBasedOnDomain signature
export type ExtractFn = (content: string, domain: string, metadata?: any) => ExtractedEntity[];
export type DetectDomainFn = (content: string) => string;
export type ParseFrontmatterFn = (content: string) => any | null;

export interface SyncPipelineConfig {
  client: MnemosyneClient;
  extractFn: ExtractFn;
  detectDomainFn: DetectDomainFn;
  parseFrontmatterFn: ParseFrontmatterFn;
  /** Debounce interval in ms (default 500) */
  debounceMs?: number;
}

// @MX:ANCHOR: [AUTO] Core real-time sync pipeline — debounce, diff, post, emit
// @MX:REASON: Called from index.ts on every note change and explicit save — fan_in >= 3
export class SyncPipeline {
  private client: MnemosyneClient;
  private extractFn: ExtractFn;
  private detectDomainFn: DetectDomainFn;
  private parseFrontmatterFn: ParseFrontmatterFn;
  private differ: EntityDiffer;
  private debounceMs: number;

  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingContent: string | null = null;
  private pendingNoteId: string | null = null;

  private graphUpdatedCallbacks: GraphUpdatedCallback[] = [];
  private statusChangeCallbacks: StatusChangeCallback[] = [];

  // Local entity store for graph view updates
  private localEntities: Map<string, KnowledgeGraphEntity> = new Map();

  // Track last known mnemosyne availability
  private mnemosyneAvailable: boolean = false;

  constructor(config: SyncPipelineConfig) {
    this.client = config.client;
    this.extractFn = config.extractFn;
    this.detectDomainFn = config.detectDomainFn;
    this.parseFrontmatterFn = config.parseFrontmatterFn;
    this.debounceMs = config.debounceMs ?? 500;
    this.differ = new EntityDiffer();
  }

  /**
   * Set mnemosyne availability from external health checks.
   */
  setMnemosyneAvailable(available: boolean): void {
    this.mnemosyneAvailable = available;
    this.emitStatusChange(available ? 'connected' : 'unavailable');
  }

  /**
   * Handle content change from note editor.
   * Debounced by default — accumulates changes and processes after debounceMs.
   */
  onContentChange(noteId: string, content: string): void {
    // Store pending content, replacing any previous pending change
    this.pendingContent = content;
    this.pendingNoteId = noteId;

    // Reset debounce timer
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }

    this.debounceTimer = setTimeout(() => {
      this.flushPending();
    }, this.debounceMs);
  }

  /**
   * Force-flush any pending content change, bypassing debounce.
   * Called on explicit save.
   */
  async forceFlush(): Promise<void> {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    await this.flushPending();
  }

  /**
   * Process pending content immediately.
   */
  private async flushPending(): Promise<void> {
    const content = this.pendingContent;
    const noteId = this.pendingNoteId;
    this.pendingContent = null;
    this.pendingNoteId = null;

    if (!content || !noteId) return;

    await this.processContent(noteId, content);
  }

  /**
   * Core processing: extract, diff, post, emit.
   */
  private async processContent(noteId: string, content: string): Promise<void> {
    // Parse frontmatter for scope metadata
    const metadata = this.parseFrontmatterFn(content);

    // Detect domain
    const domain = this.detectDomainFn(content);

    // Extract entities
    const extracted = this.extractFn(content, domain, metadata || undefined);

    // Diff against previous state
    const diff = this.differ.diff(noteId, extracted);

    // If nothing changed, skip posting
    if (diff.added.length === 0 && diff.removed.length === 0) {
      return;
    }

    // Convert to KnowledgeGraphEntity format
    const kgEntities: KnowledgeGraphEntity[] = diff.added.map(e => ({
      id: `${e.type}:${e.name}`,
      type: e.type,
      name: e.name,
      properties: e.properties,
      version: 1,
      scope_id: e.scope_id,
      source_channel: e.source_channel,
    }));

    // Update local entity store
    for (const entity of kgEntities) {
      this.localEntities.set(entity.id, entity);
    }
    // Remove entities that were removed from the note
    for (const key of diff.removed) {
      this.localEntities.delete(key);
    }

    // Post to mnemosyne if available
    if (this.mnemosyneAvailable && kgEntities.length > 0) {
      this.emitStatusChange('syncing');
      try {
        await this.client.createEntities(kgEntities);
        this.emitStatusChange('connected');
      } catch (error: any) {
        console.warn('Sync pipeline: failed to post entities to mnemosyne:', error?.message || error);
        this.mnemosyneAvailable = false;
        this.emitStatusChange('unavailable');
      }
    }

    // Emit graph-updated event with all local entities and diff info
    const allEntities = Array.from(this.localEntities.values());
    for (const cb of this.graphUpdatedCallbacks) {
      cb({
        entities: allEntities,
        diff,
        noteId,
      });
    }
  }

  /**
   * Register a callback for graph-updated events.
   */
  onGraphUpdated(callback: GraphUpdatedCallback): void {
    this.graphUpdatedCallbacks.push(callback);
  }

  /**
   * Register a callback for status changes.
   */
  onStatusChange(callback: StatusChangeCallback): void {
    this.statusChangeCallbacks.push(callback);
  }

  /**
   * Clean up state for a closed note.
   */
  onNoteClose(noteId: string): void {
    this.differ.clearNote(noteId);
  }

  /**
   * Get entity count for a specific note.
   */
  getEntityCount(noteId: string): number {
    return this.differ.getEntityCount(noteId);
  }

  /**
   * Get the underlying EntityDiffer (for testing).
   */
  getDiffer(): EntityDiffer {
    return this.differ;
  }

  /**
   * Destroy the pipeline, cleaning up timers.
   */
  destroy(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.graphUpdatedCallbacks = [];
    this.statusChangeCallbacks = [];
    this.localEntities.clear();
  }

  private emitStatusChange(status: SyncStatus): void {
    for (const cb of this.statusChangeCallbacks) {
      cb(status);
    }
  }
}
