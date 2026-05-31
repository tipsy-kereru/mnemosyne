---
id: SPEC-PERF-001
version: "0.1.0"
status: planned
created: "2026-06-01 01:40:00 NZST"
updated: "2026-06-01 01:40:00 NZST"
author: Moon Cell Harness
priority: high
risk: medium
owner_role: Performance Architect
reviewer_role: Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-PERF-001.md
---

# SPEC-PERF-001: Hybrid Performance Optimization & SQLite Database Tuning

Generated: 2026-06-01 01:40:00 NZST
Updated: 2026-06-01 01:40:00 NZST

Canonical location: `.moon-cell/specs/SPEC-PERF-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Planned |
| Implementation started | No |
| Promotion gate | User approval and harness planning |
| Related specs | SPEC-WIKI-008, SPEC-JOPLIN-004 |

## 1. Problem Statement

As the size of the Markdown wiki vault and SQLite database grows, write operations (`add`, `update`, `rebuild_from_graph`) suffer from performance degradation. This is caused by:
1. **SQLite Write Bottlenecks**: Default SQLite connection settings use rollback journal modes that lock the DB during writes.
2. **Synchronous File I/O in Python**: Re-building `index.md` and writing multiple entity pages are processed sequentially in a single thread, blocking editor interactions.
3. **AST Parser Overhead**: Navigating syntax trees in Python for deterministic code extraction creates memory/runtime overhead on large source folders.

## 2. Goals

- Reduce SQLite write latency during ingestion by at least 50%.
- Decouple the real-time editor bridge (Joplin API) from heavy Python LLM/SLM extraction tasks.
- Establish a Rust-based parallel I/O and AST parsing module (`mnemosyne-core`) to offload Python interpreter CPU bottleneck.
- Ensure zero regression in data schema, wiki formats, and unit test pass rates.

## 3. Non-Goals

- Replacing the entire codebase with Rust or Go (keep the core system in Python).
- Modifying the public CLI or external HTTP API formats.
- Changing the SQLite database engine to a client-server database (e.g., PostgreSQL).

## 4. Requirements

### REQ-PERF-001: SQLite DB Write-Ahead Logging (WAL) Tuning
- **EARS**: When initializing `KnowledgeGraph` in `knowledge_graph.py`, the system shall execute `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` to avoid full disk flushes on every write.

### REQ-PERF-002: Rust core library (PyO3) integration
- **EARS**: The system shall implement a `mnemosyne-core` Rust extension that exposes:
  - Parallel globbing and reading of Markdown files (using `Rayon`).
  - AST-based entity/relation extraction using Tree-sitter in Rust.
  - A fast index generator to replace `llm_wiki.py` `_write_index()`.

### REQ-PERF-003: Editor Decoupled Architecture (Fast-Path / Slow-Path)
- **EARS**: The `mnemosyne serve` app shall implement:
  - **Fast-Path**: Real-time editor sync requests are handled purely by the Rust core (AST-based parsing + RAM cache / SQLite staging).
  - **Slow-Path**: Expensive semantic extraction (GLiNER2 / LLMs) is pushed to a background task queue (Celery, asyncio queue, or SQLite staging table).

### REQ-PERF-004: RAM Disk and Lock Optimization
- **EARS**: Lock files and temporary staging markdown files shall be configured to write to `/tmp` (or memory-backed `tmpfs`) rather than standard magnetic/network storage.

## 5. Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-PERF-001-T1 | Performance Architect | Finalize Rust-Python interaction schema | Review design document |
| SPEC-PERF-001-T2 | Solution Architect | Apply SQLite PRAGMA configurations | Run database read/write benchmarks |
| SPEC-PERF-001-T3 | Implementer | Create `mnemosyne-core` Rust library with PyO3/Maturin | Check Pytest coverage on Rust-offloaded paths |
| SPEC-PERF-001-T4 | Test Architect | Create large vault benchmark tests | Verify no regression in test suite and latency decrease |

## 6. Definition of Done

- 526+ unit tests pass successfully.
- Baseline ingestion tests show a >50% throughput improvement.
- Ruff/Mypy pass cleanly on Python code, and cargo clippy passes on Rust code.
