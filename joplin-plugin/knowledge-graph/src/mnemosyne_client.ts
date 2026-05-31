/*
 * Mnemosyne HTTP API Client
 *
 * SPEC-JOPLIN-002 REQ-S2-002
 * HTTP client for mnemosyne serve API running on localhost.
 * Uses Node.js built-in fetch (Node 18+). No external dependencies.
 */

import { LRUCache, CACHE_TTL } from './cache';

// @MX:ANCHOR: [AUTO] Core entity and relation types shared with index.ts
// @MX:REASON: Defines the API response contract used by index.ts, cache layer, and test mocks
export interface KnowledgeGraphEntity {
  id: string;
  type: string;
  name: string;
  properties: Record<string, any>;
  version: number;
  scope_id?: string;
  source_channel?: string;
}

export interface KnowledgeGraphRelation {
  id: string;
  source: string;
  target: string;
  relationType: string;
  properties: Record<string, any>;
  scope_id?: string;
  source_channel?: string;
}

// @MX:ANCHOR: [AUTO] MnemosyneClient is the primary data access layer for the plugin
// @MX:REASON: All index.ts data reads route through this client; fan_in >= 5 (search, load, link picker, graph view, extraction)
export class MnemosyneClient {
  private baseUrl: string;
  private cache: LRUCache<any>;

  constructor(baseUrl: string = 'http://127.0.0.1:57832') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.cache = new LRUCache(500);
  }

  async health(): Promise<{ status: string; version: string }> {
    return this.request<{ status: string; version: string }>(
      '/api/v1/health',
      'GET',
      CACHE_TTL.HEALTH,
    );
  }

  async getEntities(type?: string, scopeId?: string): Promise<KnowledgeGraphEntity[]> {
    const params = new URLSearchParams();
    if (type) params.set('type', type);
    if (scopeId) params.set('scope_id', scopeId);
    const qs = params.toString();
    const path = `/api/v1/entities${qs ? '?' + qs : ''}`;

    return this.request<KnowledgeGraphEntity[]>(path, 'GET', CACHE_TTL.ENTITY);
  }

  async getEntity(id: string): Promise<KnowledgeGraphEntity | null> {
    try {
      return await this.request<KnowledgeGraphEntity>(
        `/api/v1/entities/${encodeURIComponent(id)}`,
        'GET',
        CACHE_TTL.ENTITY,
      );
    } catch (error: any) {
      if (error instanceof MnemosyneApiError && error.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async searchEntities(query: string, limit?: number): Promise<KnowledgeGraphEntity[]> {
    const params = new URLSearchParams();
    params.set('q', query);
    if (limit !== undefined) params.set('limit', String(limit));
    const path = `/api/v1/search?${params.toString()}`;

    return this.request<KnowledgeGraphEntity[]>(path, 'GET', CACHE_TTL.SEARCH);
  }

  async queryGraph(queryStr: string): Promise<any> {
    const params = new URLSearchParams();
    params.set('query', queryStr);

    return this.request<any>(
      `/api/v1/graph/query?${params.toString()}`,
      'GET',
      CACHE_TTL.SEARCH,
    );
  }

  async getRelations(filters?: {
    source?: string;
    target?: string;
    type?: string;
  }): Promise<KnowledgeGraphRelation[]> {
    const params = new URLSearchParams();
    if (filters?.source) params.set('source', filters.source);
    if (filters?.target) params.set('target', filters.target);
    if (filters?.type) params.set('type', filters.type);
    const qs = params.toString();
    const path = `/api/v1/relations${qs ? '?' + qs : ''}`;

    return this.request<KnowledgeGraphRelation[]>(path, 'GET', CACHE_TTL.ENTITY);
  }

  async getBacklinks(entityId: string): Promise<KnowledgeGraphRelation[]> {
    return this.request<KnowledgeGraphRelation[]>(
      `/api/v1/entities/${encodeURIComponent(entityId)}/backlinks`,
      'GET',
      CACHE_TTL.ENTITY,
    );
  }

  async getStats(): Promise<any> {
    return this.request<any>('/api/v1/stats', 'GET', CACHE_TTL.STATS);
  }

  async isAvailable(): Promise<boolean> {
    try {
      await this.health();
      return true;
    } catch {
      return false;
    }
  }

  // @MX:NOTE: [AUTO] POST extracted entities to mnemosyne. Non-critical — failures are logged, not thrown.
  async createEntities(entities: KnowledgeGraphEntity[]): Promise<boolean> {
    try {
      await this.fetchRaw('/api/v1/entities', 'POST', entities);
      // Invalidate entity caches after write (cache keys include method prefix)
      this.cache.invalidateByPrefix('GET:/api/v1/entities');
      this.cache.invalidateByPrefix('GET:/api/v1/search');
      return true;
    } catch (error: any) {
      console.warn('Failed to create entities in mnemosyne:', error?.message || error);
      return false;
    }
  }

  // Invalidate all cached data
  invalidateCache(): void {
    this.cache.clear();
  }

  // Invalidate caches that may be affected by entity changes
  invalidateEntityCaches(): void {
    this.cache.invalidateByPrefix('GET:/api/v1/entities');
    this.cache.invalidateByPrefix('GET:/api/v1/search');
    this.cache.invalidateByPrefix('GET:/api/v1/stats');
  }

  // --- Internal helpers ---

  private async request<T>(path: string, method: string, cacheTtl: number): Promise<T> {
    const cacheKey = `${method}:${path}`;
    const cached = this.cache.get(cacheKey);
    if (cached !== undefined) {
      return cached as T;
    }

    const result = await this.fetchRaw<T>(path, method);
    this.cache.set(cacheKey, result, cacheTtl);
    return result;
  }

  // @MX:WARN: [AUTO] Uses built-in fetch without AbortController timeout
  // @MX:REASON: AbortController adds complexity for marginal gain in desktop plugin context; latency target is <100ms localhost
  private async fetchRaw<T>(path: string, method: string, body?: any): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const options: RequestInit = {
      method,
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
    };

    if (body !== undefined) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      throw new MnemosyneApiError(
        `Mnemosyne API error: ${response.status} ${response.statusText}`,
        response.status,
      );
    }

    return response.json() as Promise<T>;
  }
}

// Custom error for API failures
export class MnemosyneApiError extends Error {
  public readonly statusCode: number;

  constructor(message: string, statusCode: number) {
    super(message);
    this.name = 'MnemosyneApiError';
    this.statusCode = statusCode;
  }
}
