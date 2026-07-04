# Mnemosyne Enhancement Specifications: GBrain Integration Phase 1

## Document Version
- **Version**: 1.0.0
- **Created**: 2025-07-04
- **Status**: Draft
- **Author**: Mnemosyne Project Team

---

## Table of Contents

1. [Overview](#overview)
2. [Phase 1: Hybrid Search Architecture](#phase-1-hybrid-search-architecture)
3. [Phase 2: Schema Pack System](#phase-2-schema-pack-system)
4. [Phase 3: Auto-Link on Write](#phase-3-auto-link-on-write)
5. [Phase 4: Job Queue (Minions)](#phase-4-job-queue-minions)
6. [Phase 5: Bi-Temporal Ontology](#phase-5-bi-temporal-ontology)
7. [Implementation Roadmap](#implementation-roadmap)
8. [Testing Strategy](#testing-strategy)

---

## Overview

### Purpose

This document specifies how Mnemosyne should integrate high-impact features from GBrain to enhance its capabilities as a knowledge graph memory system for AI agents.

### Priority Framework

Features are prioritized by:
1. **Impact on retrieval quality** (measurable improvement)
2. **Structural expressiveness** (new query capabilities)
3. **Implementation complexity** (risk vs. reward)
4. **User value** (visible improvements)

### Target State

```
Before: Mnemosyne (Current)
├── SQLite FTS5 search
├── Fixed domain schemas
├── Manual wiki-linking
├── No background processing
└── Simple temporal tracking

After: Mnemosyne Enhanced
├── Hybrid: Vector + BM25 + RRF + Reranker
├── Pluggable schema packs (agent-authored)
├── Auto-linking on every write
├── Job queue with durable subagents
└── Bi-temporal ontology with time-travel
```

---

## Phase 1: Hybrid Search Architecture

### 1.1 Current State

**Mnemosyne Today:**
```python
# mnemosyne/graph/knowledge_graph.py
def query(self, query_str: str) -> List[Entity]:
    # FTS5 BM25 search only
    cursor.execute("""
        SELECT entity_id, name, type, properties
        FROM entities_fts
        WHERE entities_fts MATCH ?
        ORDER BY bm25(entities_fts) LIMIT ?
    """, (query_str, limit))
```

**Limitations:**
- Single retrieval strategy (BM25 only)
- No semantic similarity
- Poor performance on synonym queries
- No ranked fusion of multiple signals

### 1.2 GBrain Implementation Analysis

**GBrain's Hybrid Stack:**
```typescript
// From gbrain/docs/architecture/RETRIEVAL.md
Pipeline:
  1. Intent classification (entity/temporal/event/general)
  2. Query expansion (optional LLM variants)
  3. Hybrid search:
     - Vector (HNSW on pgvector)
     - BM25 keyword (tsvector)
     - Source-aware re-rank (CASE in SQL)
     - RRF fusion → top 30
  4. Graph augment (typed-edge traversal)
  5. Reranker (zerank-2 cross-encoder)
  6. Token-budget enforcement
  7. Deduplication
```

**Key Insights:**
- RRF (Reciprocal Rank Fusion) merges rankings without global weighting
- Per-page max-pool prevents chunk dilution
- Title boost and alias hop for named entities
- Source-aware ranking prioritizes curated content

### 1.3 Proposed Architecture for Mnemosyne

#### 1.3.1 Component Structure

```
mnemosyne/
├── retrieval/
│   ├── __init__.py
│   ├── engine.py              # Main orchestration
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── vector.py          # Vector similarity
│   │   ├── bm25.py            # FTS5 keyword search
│   │   ├── graph.py           # Graph traversal
│   │   └── fusion.py          # RRF implementation
│   ├── rerank/
│   │   ├── __init__.py
│   │   └── cross_encoder.py   # Optional reranker
│   └── intent.py              # Query intent classifier
```

#### 1.3.2 Database Schema Changes

```sql
-- New tables for hybrid search
CREATE TABLE IF NOT EXISTS embeddings (
    entity_id TEXT PRIMARY KEY,
    vector BLOB,  -- Serialized numpy array or separate vector DB
    model TEXT NOT NULL,
    embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
);

CREATE TABLE IF NOT EXISTS search_cache (
    cache_key TEXT PRIMARY KEY,
    results JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hits INTEGER DEFAULT 0,
    expires_at TIMESTAMP
);

-- Existing FTS5 table gets auxiliary columns
ALTER TABLE entities_fts ADD COLUMN source_boost REAL DEFAULT 1.0;
ALTER TABLE entities_fts ADD COLUMN title_boost REAL DEFAULT 1.0;
```

#### 1.3.3 API Design

```python
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class SearchMode:
    """Search mode bundles cost/quality knobs"""
    name: str  # conservative, balanced, tokenmax
    use_vector: bool = True
    use_reranker: bool = False
    use_expansion: bool = False
    max_results: int = 30
    token_budget: Optional[int] = None

@dataclass
class SearchResult:
    """Unified result with evidence tags"""
    entity_id: str
    score: float
    evidence: List[str]  # ['vector_match', 'keyword_exact', 'title_hit']
    create_safety: str  # 'exists', 'probable', 'unknown'
    source_strategy: str  # which strategy surfaced this

class RetrievalEngine:
    """Main orchestration engine"""

    def __init__(self, db_path: str, mode: SearchMode):
        self.db_path = db_path
        self.mode = mode
        self.strategies = self._init_strategies()

    def query(
        self,
        query_str: str,
        filters: Optional[Dict] = None,
        explain: bool = False
    ) -> List[SearchResult]:
        """
        Execute hybrid search query

        Args:
            query_str: Search query
            filters: Optional entity type filters
            explain: If True, return scoring attribution

        Returns:
            List of SearchResult with evidence tags
        """
        # 1. Intent classification
        intent = self._classify_intent(query_str)

        # 2. Query expansion (if enabled)
        queries = self._maybe_expand(query_str, intent)

        # 3. Run all strategies in parallel
        strategy_results = self._run_strategies(queries, filters)

        # 4. RRF fusion
        fused = self._rrf_fusion(strategy_results)

        # 5. Graph augmentation (if applicable)
        augmented = self._graph_augment(fused, intent)

        # 6. Rerank (if enabled)
        ranked = self._rerank(augmented, query_str)

        # 7. Apply evidence tags
        tagged = self._add_evidence(ranked, strategy_results)

        return tagged

    def _rrf_fusion(
        self,
        strategy_results: Dict[str, List[Tuple[str, float]]],
        k: int = 60
    ) -> List[Tuple[str, float]]:
        """
        Reciprocal Rank Fusion

        Formula: score = sum(1 / (k + rank))

        Args:
            strategy_results: {strategy_name: [(entity_id, raw_score), ...]}
            k: RRF constant (default 60)

        Returns:
            [(entity_id, fused_score), ...] sorted by fused_score
        """
        fused_scores: Dict[str, float] = {}

        for strategy, results in strategy_results.items():
            for rank, (entity_id, _) in enumerate(results, start=1):
                if entity_id not in fused_scores:
                    fused_scores[entity_id] = 0.0
                fused_scores[entity_id] += 1.0 / (k + rank)

        return sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
```

#### 1.3.4 Vector Strategy Implementation

```python
# mnemosyne/retrieval/strategies/vector.py
import numpy as np
from typing import List, Tuple

class VectorStrategy:
    """Vector similarity search using embeddings"""

    def __init__(self, db_path: str, model_name: str = "all-MiniLM-L6-v2"):
        self.db_path = db_path
        self.model_name = model_name
        self.embedding_dim = self._get_model_dim()
        self._init_index()

    def _get_model_dim(self) -> int:
        """Get embedding dimension for model"""
        # Map model names to dimensions
        DIMENSIONS = {
            "all-MiniLM-L6-v2": 384,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }
        return DIMENSIONS.get(self.model_name, 384)

    def search(
        self,
        query: str,
        limit: int = 30,
        filters: Optional[Dict] = None
    ) -> List[Tuple[str, float]]:
        """
        Search by vector similarity

        Returns: [(entity_id, similarity_score), ...]
        """
        # 1. Embed query
        query_embedding = self._embed(query)

        # 2. Fetch candidate embeddings
        candidates = self._fetch_candidates(filters)

        # 3. Compute cosine similarity
        scores = []
        for entity_id, embedding in candidates:
            similarity = self._cosine_similarity(query_embedding, embedding)
            scores.append((entity_id, similarity))

        # 4. Return top-k
        return sorted(scores, key=lambda x: x[1], reverse=True)[:limit]

    def _embed(self, text: str) -> np.ndarray:
        """Generate embedding for text"""
        # Use sentence-transformers or OpenAI embeddings
        # This is a placeholder for the actual implementation
        pass

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors"""
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
```

#### 1.3.5 Implementation Phases

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **1.1** | RRF fusion engine | 3 days | None |
| **1.2** | Vector strategy with local embeddings | 5 days | sentence-transformers |
| **1.3** | Enhanced BM25 with title/alias boost | 2 days | None |
| **1.4** | Per-page max-pool for chunked content | 3 days | Vector strategy |
| **1.5** | Optional cross-encoder reranker | 5 days | Vector strategy |
| **1.6** | Intent classifier | 2 days | None |
| **1.7** | Query expansion (optional) | 3 days | Intent classifier |

**Total Estimated Effort: 23 days**

### 1.4 Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| P@5 on named-entity queries | ~18% | 40%+ | Internal benchmark |
| Recall on synonym queries | ~65% | 85%+ | Internal benchmark |
| Average query latency | <50ms | <200ms | Performance test |
| Coverage of chunked content | Single chunk | Best page | Code test |

### 1.5 Migration Strategy

1. **Dual-read mode**: Old and new engines run in parallel during transition
2. **Feature flags**: `MNEMOSYNE_USE_HYBRID_SEARCH=1` to opt in
3. **Gradual rollout**: 10% → 50% → 100% of queries
4. **Fallback**: Any failure falls back to BM25 only
5. **Monitoring**: Log query outcomes to `mnemosyne/retrieval/audit.log`

---

## Phase 2: Schema Pack System

### 2.1 Current State

**Mnemosyne Today:**
```python
# mnemosyne/schema/base.md - Fixed schema files
# Schemas are read-only, defined in markdown
# Entity types are hardcoded in extraction pipelines
```

**Limitations:**
- Cannot add new types without code changes
- No agent-authored schema evolution
- Fixed relationship types
- No extractable/expert routing flags

### 2.2 GBrain Implementation Analysis

**GBrain's Schema System:**
```yaml
# gbrain-base-v2 pack example
types:
  person:
    primitive: entity
    prefix: people/
    extractable: true
    expert_routing: true
    properties:
      - name
      - role
      - contact

link_types:
  works_at:
    from: person
    to: company
    inferred: true
```

**Key Features:**
- Packs are versioned YAML files
- Agents can author new packs via MCP
- Atomic schema mutations with audit trail
- Backfill support for existing pages

### 2.3 Proposed Architecture for Mnemosyne

#### 2.3.1 Schema Pack Structure

```
~/.mnemosyne/schema-packs/
├── builtin/
│   ├── base-v1/
│   │   └── pack.yaml
│   └── coding-v1/
│       └── pack.yaml
└── custom/
    ├── my-brain-v1/
    │   └── pack.yaml
    └── ACTIVE  # Symlink to active pack
```

#### 2.3.2 Pack Schema Definition

```yaml
# pack.yaml
api_version: "1.0"
name: "my-brain"
version: "1.0"
inherits: "base-v1"  # Optional: extend another pack

# Entity type definitions
types:
  person:
    description: "A person entity"
    primitive: entity  # entity | temporal | annotation
    prefix_patterns:
      - "people/**"
      - "contacts/**"
    extractable: true     # Run fact extraction
    expert_routing: true  # Use for expert search
    properties:
      - name: string
      - role: string
      - email: string
      - contact: string

  meeting:
    description: "A meeting or conversation"
    primitive: temporal
    prefix_patterns:
      - "meetings/**"
      - "conversations/**"
    extractable: true
    expert_routing: true
    properties:
      - title: string
      - date: datetime
      - attendees: list[person]
      - duration: interval

# Relationship type definitions
link_types:
  works_at:
    description: "Person works at organization"
    from: person
    to: company
    inferred: true  # Auto-infer from context

  attended:
    description: "Person attended meeting"
    from: person
    to: meeting
    inferred: true

# Search mode overrides
search_defaults:
  use_graph: true
  use_reranker: false
  max_results: 20
```

#### 2.3.3 Schema Engine API

```python
# mnemosyne/schema/engine.py
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class EntityType:
    """Entity type definition"""
    name: str
    primitive: str  # entity | temporal | annotation
    prefix_patterns: List[str]
    extractable: bool
    expert_routing: bool
    properties: Dict[str, str]

@dataclass
class LinkType:
    """Relationship type definition"""
    name: str
    from_type: str
    to_type: str
    inferred: bool
    description: str

@dataclass
class SchemaPack:
    """Complete schema pack"""
    name: str
    version: str
    inherits: Optional[str]
    types: Dict[str, EntityType]
    link_types: Dict[str, LinkType]
    search_defaults: Dict

class SchemaEngine:
    """Schema management and resolution"""

    def __init__(self, packs_dir: Path):
        self.packs_dir = packs_dir
        self.active_pack: Optional[SchemaPack] = None
        self._pack_cache: Dict[str, SchemaPack] = {}

    def load_pack(self, pack_name: str) -> SchemaPack:
        """Load a schema pack from disk"""
        pack_path = self.packs_dir / pack_name / "pack.yaml"
        # Parse YAML, resolve inheritance, validate
        pass

    def set_active(self, pack_name: str) -> None:
        """Set the active schema pack"""
        self.active_pack = self.load_pack(pack_name)
        self._write_active_link(pack_name)

    def infer_type(self, file_path: str) -> Optional[str]:
        """
        Infer entity type from file path using active pack

        Returns: Type name or None
        """
        if not self.active_pack:
            return None

        for type_name, type_def in self.active_pack.types.items():
            for pattern in type_def.prefix_patterns:
                if self._match_pattern(file_path, pattern):
                    return type_name
        return None

    def is_extractable(self, type_name: str) -> bool:
        """Check if type should have fact extraction"""
        type_def = self.active_pack.types.get(type_name)
        return type_def.extractable if type_def else False

    def is_expert_routing(self, type_name: str) -> bool:
        """Check if type should route through expert search"""
        type_def = self.active_pack.types.get(type_name)
        return type_def.expert_routing if type_def else False
```

#### 2.3.4 MCP Operations for Schema Evolution

```python
# mnemosyne/mcp/schema_ops.py
class SchemaOperations:
    """MCP operations for schema authoring"""

    def register(self, server) -> None:
        """Register schema operations with MCP server"""

        @server.tool()
        def schema_add_type(
            name: str,
            primitive: str,
            prefix_patterns: List[str],
            extractable: bool = False,
            expert_routing: bool = False
        ) -> dict:
            """
            Add a new entity type to the custom schema pack

            Creates or updates the custom pack with a new type definition.
            Requires admin scope for security.
            """
            pass

        @server.tool()
        def schema_sync(
            apply: bool = False,
            backfill: bool = True
        ) -> dict:
            """
            Sync schema changes to the knowledge graph

            If apply=False, returns a dry-run plan.
            If backfill=True, updates existing entities with new types.
            """
            pass

        @server.tool()
        def schema_detect(
            limit: int = 100
        ) -> dict:
            """
            Detect untyped pages that share common patterns

            Returns candidates for new type definitions.
            """
            pass
```

#### 2.3.5 Implementation Phases

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **2.1** | Schema pack file format and parser | 4 days | PyYAML |
| **2.2** | Schema engine with type inference | 5 days | Phase 2.1 |
| **2.3** | Pack activation and inheritance | 3 days | Phase 2.1 |
| **2.4** | MCP operations for schema evolution | 4 days | Phase 2.2 |
| **2.5** | Backfill pipeline for type changes | 3 days | Phase 2.2 |
| **2.6** | Extractable flag integration | 3 days | Phase 2.2 |
| **2.7** | Expert routing integration | 2 days | Phase 2.2, Phase 1 |

**Total Estimated Effort: 24 days**

### 2.4 Migration Strategy

1. **Default pack migration**: Convert existing schemas to pack format
2. **Backfill default**: All existing installations get `base-v1` pack
3. **Feature flag**: `MNEMOSYNE_USE_SCHEMA_PACKS=1`
4. **Gradual migration**: First new installs, then existing

---

## Phase 3: Auto-Link on Write

### 3.1 Current State

**Mnemosyne Today:**
- Wiki links must be manually written
- No automatic relationship extraction
- Link syntax parsed but not auto-created

### 3.2 GBrain Implementation Analysis

**GBrain's Auto-Link:**
```typescript
// Zero LLM call link extraction
// Matches: [text](path), [[path]], typed links
// Inferred types: attended, works_at, invested_in
```

**Key Features:**
- Regex-based entity reference extraction
- Zero LLM overhead
- Batch SQL insert for edges
- Heuristic type inference

### 3.3 Proposed Architecture for Mnemosyne

#### 3.3.1 Link Extraction Patterns

```python
# mnemosyne/link/extractor.py
import re
from typing import List, Tuple

class LinkExtractor:
    """Extract entity references from markdown"""

    # Patterns for different link syntaxes
    PATTERNS = [
        r'\[([^\]]+)\]\(([^)]+)\)',  # [text](path)
        r'\[\[([^\]]+)\]\]',         # [[path]]
        r'\[\[([^\]]+)\|([^\]]+)\]\]',  # [[path|label]]
    ]

    # Context patterns for type inference
    TYPE_PATTERNS = {
        'works_at': r'(?:works? at|employed by|joining) (\w+)',
        'attended': r'(?:attended|met with|joined) (\w+)',
        'authored': r'(?:authored|wrote|created) (\w+)',
    }

    def extract_links(self, markdown: str) -> List[Tuple[str, str, str]]:
        """
        Extract all entity references from markdown

        Returns: [(link_text, target_path, context), ...]
        """
        pass

    def infer_link_type(
        self,
        source_type: str,
        target_path: str,
        context: str
    ) -> Optional[str]:
        """
        Infer link type from context

        Returns: Link type or None
        """
        pass
```

#### 3.3.2 Auto-Link Integration

```python
# mnemosyne/link/auto_linker.py
class AutoLinker:
    """Automatically create links on entity writes"""

    def __init__(self, kg: KnowledgeGraph, schema: SchemaEngine):
        self.kg = kg
        self.schema = schema

    def on_entity_write(self, entity_id: str, content: str) -> None:
        """
        Process entity write and create auto-links

        Called automatically by KnowledgeGraph.add_entity()
        """
        # 1. Extract links from content
        links = self.extractor.extract_links(content)

        # 2. Resolve targets
        for link_text, target_path, context in links:
            target_id = self._resolve_target(target_path)
            if not target_id:
                # Create stub entity if not exists
                target_id = self._create_stub(target_path)

            # 3. Infer link type
            source_type = self.kg.get_entity_type(entity_id)
            link_type = self.extractor.infer_link_type(
                source_type, target_path, context
            )

            # 4. Create relationship
            self.kg.add_relation(
                from_entity=entity_id,
                to_entity=target_id,
                relation_type=link_type or "mentions",
                inferred=True
            )
```

#### 3.3.3 Implementation Phases

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **3.1** | Link extraction patterns | 2 days | None |
| **3.2** | Target resolution with stub creation | 2 days | Phase 3.1 |
| **3.3** | Type inference heuristics | 2 days | Phase 3.1, Phase 2 |
| **3.4** | Batch insert optimization | 1 day | Phase 3.2 |
| **3.5** | Integration with write pipeline | 2 days | Phase 3.3 |

**Total Estimated Effort: 9 days**

---

## Phase 4: Job Queue (Minions)

### 4.1 Current State

**Mnemosyne Today:**
- No background processing
- No job queue
- No durable subagents

### 4.2 GBrain Implementation Analysis

**GBrain's Minions:**
- BullMQ-shaped job queue
- Two-phase persistence (pending → done)
- Rate limiting for outbound providers
- Child jobs with cascading timeouts

### 4.3 Proposed Architecture for Mnemosyne

#### 4.3.1 Job Queue Schema

```sql
CREATE TABLE IF NOT EXISTS job_queue (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, running, done, failed
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    parent_job_id TEXT,
    FOREIGN KEY (parent_job_id) REFERENCES job_queue(job_id)
);

CREATE INDEX idx_job_queue_status ON job_queue(status, created_at);
CREATE INDEX idx_job_queue_parent ON job_queue(parent_job_id);
```

#### 4.3.2 Job Queue API

```python
# mnemosyne/jobs/queue.py
from typing import Optional, Dict, Any
from enum import Enum

class JobStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'

class JobQueue:
    """Durable job queue for background tasks"""

    def submit(
        self,
        job_type: str,
        payload: Dict[str, Any],
        parent_id: Optional[str] = None
    ) -> str:
        """Submit a job to the queue"""
        pass

    def acquire(self, limit: int = 10) -> List[Dict]:
        """Acquire pending jobs for processing"""
        pass

    def complete(self, job_id: str, result: Dict) -> None:
        """Mark job as done with result"""
        pass

    def fail(self, job_id: str, error: str) -> None:
        """Mark job as failed (will retry)"""
        pass

    def get_status(self, job_id: str) -> JobStatus:
        """Get current job status"""
        pass
```

#### 4.3.3 Job Workers

```python
# mnemosyne/jobs/worker.py
class JobWorker:
    """Background job worker"""

    def __init__(self, queue: JobQueue, concurrency: int = 4):
        self.queue = queue
        self.concurrency = concurrency
        self.handlers = self._register_handlers()

    def _register_handlers(self) -> Dict[str, callable]:
        """Register job type handlers"""
        return {
            'extract_facts': self.handle_extract_facts,
            'enrich_entity': self.handle_enrich_entity,
            'sync_source': self.handle_sync_source,
            'index_embeddings': self.handle_index_embeddings,
        }

    def run(self) -> None:
        """Main worker loop"""
        while True:
            jobs = self.queue.acquire(limit=self.concurrency)
            for job in jobs:
                self.process_job(job)

    def process_job(self, job: Dict) -> None:
        """Process a single job"""
        handler = self.handlers.get(job['job_type'])
        if not handler:
            self.queue.fail(job['job_id'], 'Unknown job type')
            return

        try:
            result = handler(job['payload'])
            self.queue.complete(job['job_id'], result)
        except Exception as e:
            self.queue.fail(job['job_id'], str(e))
```

#### 4.3.4 Implementation Phases

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **4.1** | Job queue schema and API | 3 days | None |
| **4.2** | Worker implementation | 4 days | Phase 4.1 |
| **4.3** | Retry logic with backoff | 2 days | Phase 4.1 |
| **4.4** | Child job support | 3 days | Phase 4.1 |
| **4.5** | Rate limiting | 2 days | Phase 4.2 |

**Total Estimated Effort: 14 days**

---

## Phase 5: Bi-Temporal Ontology

### 5.1 Current State

**Mnemosyne Today:**
- Simple temporal tracking (created_at, updated_at)
- No validity windows
- No time-travel queries

### 5.2 GBrain Implementation Analysis

**GBrain's Facts Table:**
```sql
-- Bi-temporal facts with validity windows
CREATE TABLE facts (
    entity_id TEXT,
    dimension TEXT,
    value TEXT,
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    source_page TEXT,
    confidence REAL
);
```

### 5.3 Proposed Architecture for Mnemosyne

#### 5.3.1 Facts Schema

```sql
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    dimension TEXT NOT NULL,  -- e.g., 'mrr', 'role', 'status'
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',  -- string, number, datetime, boolean
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP,  -- NULL means currently valid
    source_page TEXT,
    confidence REAL DEFAULT 1.0,
    superseded_by TEXT,  -- ID of newer fact that replaces this
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id),
    FOREIGN KEY (superseded_by) REFERENCES facts(fact_id)
);

CREATE INDEX idx_facts_entity ON facts(entity_id, valid_from);
CREATE INDEX idx_facts_dimension ON facts(dimension, value);
```

#### 5.3.2 Facts API

```python
# mnemosyne/facts/store.py
from typing import List, Optional
from datetime import datetime

class FactsStore:
    """Bi-temporal facts storage"""

    def add_fact(
        self,
        entity_id: str,
        dimension: str,
        value: Any,
        valid_from: datetime,
        valid_to: Optional[datetime] = None,
        confidence: float = 1.0,
        source_page: Optional[str] = None
    ) -> str:
        """Add a new fact (supersedes existing facts for this dimension)"""
        pass

    def get_facts(
        self,
        entity_id: str,
        as_of: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Get facts for entity, optionally as of a point in time

        If as_of is None, returns currently valid facts
        """
        pass

    def get_history(
        self,
        entity_id: str,
        dimension: Optional[str] = None
    ) -> List[Dict]:
        """Get full history of facts for entity"""
        pass

    def find_contradictions(self) -> List[Dict]:
        """Find conflicting facts (same dimension, different values)"""
        pass
```

#### 5.3.3 Implementation Phases

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **5.1** | Facts table schema | 2 days | None |
| **5.2** | Facts storage API | 3 days | Phase 5.1 |
| **5.3** | Time-travel queries | 3 days | Phase 5.2 |
| **5.4** | Contradiction detection | 2 days | Phase 5.2 |
| **5.5** | Integration with extraction | 2 days | Phase 5.2 |

**Total Estimated Effort: 12 days**

---

## Implementation Roadmap

### Timeline Overview

```
Phase 1: Hybrid Search      [23 days]  ████████████████████████
Phase 2: Schema Pack        [24 days]               ████████████████████████
Phase 3: Auto-Link           [ 9 days]                         ████████████
Phase 4: Job Queue          [14 days]                           ████████████████████
Phase 5: Bi-Temporal        [12 days]                                     ██████████████████
                                      └───────────────────┘
                                            Total: ~82 days
```

### Sprint Breakdown

| Sprint | Phases | Duration | Deliverables |
|--------|--------|----------|--------------|
| **Sprint 1** | 1.1-1.3 | 2 weeks | RRF + Vector + BM25 enhancements |
| **Sprint 2** | 1.4-1.5 | 2 weeks | Max-pool + Reranker |
| **Sprint 3** | 2.1-2.3 | 2 weeks | Schema pack format |
| **Sprint 4** | 2.4-2.5 | 2 weeks | MCP ops + Backfill |
| **Sprint 5** | 3.1-3.4 | 2 weeks | Auto-link complete |
| **Sprint 6** | 4.1-4.3 | 2 weeks | Job queue foundation |
| **Sprint 7** | 4.4-5.2 | 2 weeks | Child jobs + Facts API |
| **Sprint 8** | 5.3-5.5 | 2 weeks | Time-travel + Integration |

### Dependencies

```
Phase 2 (Schema Pack) ← Phase 1 (Hybrid Search)
      ↓
Phase 3 (Auto-Link) ← Phase 2 (Schema Pack)
      ↓
Phase 5 (Facts) ← Phase 2 (Schema Pack)
      ↓
Phase 4 (Job Queue) ← Phase 5 (Facts)
```

---

## Testing Strategy

### Unit Testing

- Each module has >80% coverage
- Mock external dependencies (LLM, vector DB)
- Property-based testing for fusion algorithms

### Integration Testing

- End-to-end query pipelines
- Schema evolution workflows
- Job queue processing

### Benchmark Testing

- NamedThingBench for entity retrieval
- LongMemEval for long-form retrieval
- Custom corpus for domain-specific testing

### Regression Testing

- Capture real queries
- Replay against code changes
- Automated regression detection

---

## Success Criteria

### Phase 1 Success
- [ ] P@5 improvement >20 points on internal benchmark
- [ ] Query latency <200ms p95
- [ ] Zero fallbacks to BM25-only in production

### Phase 2 Success
- [ ] New type added without code change
- [ ] Existing pages backfilled successfully
- [ ] MCP operations atomic and audited

### Phase 3 Success
- [ ] 90%+ of entity writes create auto-links
- [ ] Zero LLM calls for link extraction
- [ ] Stub entities created for unknown targets

### Phase 4 Success
- [ ] Jobs survive process crashes
- [ ] Child jobs complete when parent fails
- [ ] Rate limiting respected

### Phase 5 Success
- [ ] Time-travel queries return correct state
- [ ] Contradictions detected automatically
- [ ] Facts superseded correctly

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Vector embedding costs | High | Support local models; cost budgeting |
| Schema complexity | Medium | Start with simple packs; gradual migration |
| Job queue reliability | High | Two-phase persistence; retry logic |
| Facts table bloat | Medium | Retention policy; archiving |

---

## Appendix

### A. Related Documents

- [GBrain RETRIEVAL.md](https://github.com/garrytan/gbrain/blob/main/docs/architecture/RETRIEVAL.md)
- [GBrain what-schemas-unlock.md](https://github.com/garrytan/gbrain/blob/main/docs/what-schemas-unlock.md)
- [Mnemosyne ARCHITECTURE.md](./ARCHITECTURE.md)

### B. API Compatibility

All changes maintain backward compatibility through:
- Feature flags
- Dual-read modes
- Gradual rollout

### C. Open Questions

1. Should we support pgvector for large deployments?
2. What's the default embedding model for local use?
3. How do we handle schema pack conflicts?

---

**Document Status:** Draft — Ready for review and feedback.
