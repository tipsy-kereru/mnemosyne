/*
 * Entity Differ for SPEC-JOPLIN-004
 *
 * Compares extracted entities with previous extraction for the same note.
 * Only returns new/changed entities, skipping unchanged ones.
 * Deduplicates by type+name+scope before returning.
 * Tracks state per note ID and cleans up on note close.
 */

export interface ExtractedEntity {
  type: string;
  name: string;
  properties: Record<string, any>;
  scope_id?: string;
  source_channel?: string;
}

// Snapshot of entities previously extracted for a note
interface NoteSnapshot {
  // Map from dedup key to entity fingerprint (JSON of properties)
  fingerprints: Map<string, string>;
  // Full entities keyed by dedup key
  entities: Map<string, ExtractedEntity>;
}

// Result of diffing
export interface DiffResult {
  /** Entities that are new or changed */
  added: ExtractedEntity[];
  /** Entity keys that were removed since last extraction */
  removed: string[];
  /** Total unique entities in current extraction */
  total: number;
}

// @MX:ANCHOR: [AUTO] Entity deduplication and diffing for real-time sync
// @MX:REASON: Used by SyncPipeline on every content change and force-flush — fan_in >= 3
export class EntityDiffer {
  private snapshots: Map<string, NoteSnapshot> = new Map();

  /**
   * Build a dedup key from entity type + name + scope_id.
   * Two entities are considered the same if all three match.
   */
  static dedupKey(entity: ExtractedEntity): string {
    return `${entity.type}:${entity.name}:${entity.scope_id || ''}`;
  }

  /**
   * Compute a fingerprint for change detection.
   * Two entities with the same dedup key are "unchanged" if their
   * fingerprints match (same properties, same source_channel).
   */
  private static fingerprint(entity: ExtractedEntity): string {
    return JSON.stringify({
      properties: entity.properties,
      source_channel: entity.source_channel || '',
    });
  }

  /**
   * Diff current extraction against the previous snapshot for a note.
   * Returns only new/changed entities and removed entity keys.
   */
  diff(noteId: string, currentEntities: ExtractedEntity[]): DiffResult {
    const prev = this.snapshots.get(noteId);
    const prevFingerprints = prev?.fingerprints || new Map<string, string>();

    // Deduplicate current entities by key
    const currentMap = new Map<string, ExtractedEntity>();
    for (const entity of currentEntities) {
      const key = EntityDiffer.dedupKey(entity);
      currentMap.set(key, entity);
    }

    const added: ExtractedEntity[] = [];
    const removed: string[] = [];

    // Find new and changed entities
    for (const [key, entity] of currentMap) {
      const prevFp = prevFingerprints.get(key);
      const currentFp = EntityDiffer.fingerprint(entity);

      if (prevFp === undefined) {
        // New entity
        added.push(entity);
      } else if (prevFp !== currentFp) {
        // Changed entity
        added.push(entity);
      }
      // else: unchanged — skip
    }

    // Find removed entities
    for (const key of prevFingerprints.keys()) {
      if (!currentMap.has(key)) {
        removed.push(key);
      }
    }

    // Save new snapshot
    const newFingerprints = new Map<string, string>();
    const newEntities = new Map<string, ExtractedEntity>();
    for (const [key, entity] of currentMap) {
      newFingerprints.set(key, EntityDiffer.fingerprint(entity));
      newEntities.set(key, entity);
    }
    this.snapshots.set(noteId, {
      fingerprints: newFingerprints,
      entities: newEntities,
    });

    return { added, removed, total: currentMap.size };
  }

  /**
   * Get the current entity count for a note.
   */
  getEntityCount(noteId: string): number {
    const snapshot = this.snapshots.get(noteId);
    return snapshot?.fingerprints.size ?? 0;
  }

  /**
   * Clean up state for a closed note.
   */
  clearNote(noteId: string): void {
    this.snapshots.delete(noteId);
  }

  /**
   * Check if a note has a previous snapshot.
   */
  hasNote(noteId: string): boolean {
    return this.snapshots.has(noteId);
  }

  /**
   * Get total notes being tracked.
   */
  get noteCount(): number {
    return this.snapshots.size;
  }
}
