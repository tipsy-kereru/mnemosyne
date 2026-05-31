/*
 * LRU Cache for Mnemosyne HTTP responses
 *
 * SPEC-JOPLIN-002 REQ-S2-004
 * - Max 500 entries
 * - Configurable TTL per entry (30s entities, 10s search)
 * - Invalidation by key or full clear
 */

interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}

// @MX:ANCHOR: [AUTO] LRU cache used by MnemosyneClient for all HTTP responses
// @MX:REASON: Shared cache instance used across getEntities, searchEntities, getEntity, and getStats calls
export class LRUCache<T> {
  private cache: Map<string, CacheEntry<T>> = new Map();
  private readonly maxSize: number;

  constructor(maxSize: number = 500) {
    this.maxSize = maxSize;
  }

  get(key: string): T | undefined {
    const entry = this.cache.get(key);
    if (!entry) {
      return undefined;
    }

    if (Date.now() > entry.expiresAt) {
      this.cache.delete(key);
      return undefined;
    }

    // Move to end (most recently used) by re-inserting
    this.cache.delete(key);
    this.cache.set(key, entry);

    return entry.value;
  }

  set(key: string, value: T, ttlMs: number): void {
    // Remove existing entry to update position
    this.cache.delete(key);

    // Evict oldest entries if at capacity
    while (this.cache.size >= this.maxSize) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey !== undefined) {
        this.cache.delete(oldestKey);
      }
    }

    this.cache.set(key, {
      value,
      expiresAt: Date.now() + ttlMs,
    });
  }

  invalidate(key: string): boolean {
    return this.cache.delete(key);
  }

  // @MX:NOTE: [AUTO] Pattern-based invalidation removes entries whose key starts with prefix
  invalidateByPrefix(prefix: string): number {
    let count = 0;
    for (const key of this.cache.keys()) {
      if (key.startsWith(prefix)) {
        this.cache.delete(key);
        count++;
      }
    }
    return count;
  }

  clear(): void {
    this.cache.clear();
  }

  get size(): number {
    return this.cache.size;
  }

  // Check if a key exists and is not expired
  has(key: string): boolean {
    return this.get(key) !== undefined;
  }
}

// TTL constants
export const CACHE_TTL = {
  ENTITY: 30_000,   // 30 seconds for entity lookups
  SEARCH: 10_000,   // 10 seconds for search results
  STATS: 60_000,    // 60 seconds for stats
  HEALTH: 5_000,    // 5 seconds for health checks
} as const;
