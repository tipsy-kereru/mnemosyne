# Mnemosyne Knowledge Graph

Local-first, zero-API-cost knowledge memory system for AI agents. Provides persistent, compounding knowledge across three domains: **daily life**, **coding**, and **legal**.

Based on Google's Gemini Universal Temporal Knowledge Graph research and Andrej Karpathy's insight: *"Obsidian is the IDE, the language model is the programmer, and the wiki is the codebase."*

## Quality Status

| Metric | Status |
|--------|--------|
| Tests | 626 passed |
| Type Safety | mypy 0 errors |
| Lint | ruff 0 violations |
| Warnings | 0 pytest warnings |
| Coverage | 81%+ |
| SPECs | 19 completed, 0 in progress |

## Architecture

```
Raw Source Layer (Immutable)
       ↓
Wiki Layer (Markdown + [[wiki-links]])
       ↓
Schema Layer (CLAUDE.md / AGENTS.md)
       ↓
Knowledge Graph (SQLite + NetworkX)
```

**Four-layer extraction pipeline:**

| Layer | Technology | Cost | Hardware |
|-------|-----------|------|----------|
| Deterministic | Tree-sitter AST, SpaCy | $0 | CPU only |
| Semantic | GLiNER2 NER, REBEL | $0 | CPU / small GPU |
| Synthesis | Llama-3-8B / GPT-4o | Optional | GPU / Cloud |
| Wiki | Markdown + wiki-links | $0 | Any |

## Installation

**Requirements:** Python 3.11 or later (3.13 recommended).

### From GitHub (recommended for users)

```bash
# Install latest from GitHub
pip install "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# With ingest extras (LLM extraction, URL fetching)
pip install "mnemosyne-kg[ingest] @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# With deterministic extraction (tree-sitter, zero LLM)
pip install "mnemosyne-kg[deterministic] @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# Everything
pip install "mnemosyne-kg[all] @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

After installation, CLI commands are available:

```bash
mnemosyne --version       # verify install
mnemosyne add --help      # ingest files, URLs, or text
mnemosyne query --stats   # graph statistics
mnemosyne wiki doctor     # wiki health check
```

### Update

```bash
# pip
pip install --upgrade "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"

# uv
uv pip install --upgrade "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

### Install agent skill

Install the `/mnemosyne` skill so AI agents (Claude Code, etc.) can use knowledge graph commands directly:

```bash
# Default: install to ~/.claude/skills/mnemosyne/ (Claude Code)
mnemosyne skill install

# For other agent frameworks (global ~/.agents/skills/)
mnemosyne skill install --target agents

# Force reinstall even if identical
mnemosyne skill install --force

# Custom path
mnemosyne skill install --path ~/my-agent/skills
```

After installing, type `/mnemosyne` in Claude Code to ingest, query, extract, and manage your knowledge graph.

### From source (for contributors)

```bash
git clone https://github.com/tipsy-kereru/mnemosyne.git
cd mnemosyne

# Core only
pip install -e .

# With deterministic extraction (tree-sitter)
pip install -e ".[deterministic]"

# With semantic extraction (GLiNER2, torch)
pip install -e ".[semantic]"

# Development (lint, type-check, test)
pip install -e ".[dev]"

# Everything
pip install -e ".[all]"
```

### Extras

| Extra | Includes | Use Case |
|-------|----------|----------|
| `deterministic` | tree-sitter, SpaCy | Zero-LLM code extraction |
| `semantic` | GLiNER2, torch, transformers | Local SLM entity extraction |
| `ingest` | requests, anthropic, httpx | URL fetching, LLM-based extraction |
| `all` | deterministic + semantic | Full local extraction |
| `dev` (dependency-group) | pytest, ruff, tree-sitter, all ingest deps | Contributing |

## Quick Start

```bash
# 1. Install from GitHub
pip install "mnemosyne-kg[all] @ git+https://github.com/tipsy-kereru/mnemosyne.git"
# or from a local clone:
# pip install -e ".[all]"

# 2. Add a source to the knowledge graph and the LLM Wiki
mnemosyne add ./notes/meeting.md --domain daily
# graph  → ~/mnemosyne/graph/knowledge.db
# wiki   → ~/mnemosyne/wiki/{index.md,log.md,sources/,entities/}

# 3. Query the knowledge graph
mnemosyne query --stats
mnemosyne query --query "search:authenticate"
mnemosyne query --query "entity:function[parse_config]"

# 4. Extract code entities from a project
mnemosyne extract src/ --domain coding --format json

# 5. Check wiki health
mnemosyne wiki doctor
```

## CLI Reference

### Top-level commands

| Command | Description |
|---------|-------------|
| `mnemosyne --version` | Show package version |
| `mnemosyne query --stats` | Graph statistics |
| `mnemosyne query --query "search:term"` | FTS5 fuzzy search (ranked results) |
| `mnemosyne extract <path>` | Extract entities from a file or directory |
| `mnemosyne add <target>` | Ingest a file, directory, URL, or `--text` snippet |
| `mnemosyne update <path>` | Incrementally refresh graph and LLM Wiki from changed files |
| `mnemosyne wiki <subcommand>` | Inspect and maintain the Markdown LLM Wiki |
| `mnemosyne mcp serve` | Start MCP server for AI agent integration |

### `mnemosyne add` options

| Option | Default | Description |
|--------|---------|-------------|
| `--text TEXT` | — | Ingest an inline text snippet instead of a file/URL |
| `--domain {coding,daily,legal}` | `daily` | Domain for ingestion |
| `--scope-id ID` | — | Attach a named scope to ingested entities |
| `--source-channel CHANNEL` | `cli` | Tag the ingestion source |
| `--dry-run` | off | Preview extraction without writing to the graph |
| `--wiki-root PATH` | `~/mnemosyne/wiki` | LLM Wiki root directory |
| `--no-wiki` | off | Update the knowledge graph only; skip wiki pages |
| `--wiki-excerpts` | off | Opt in to bounded, redacted source excerpts in wiki pages |

Default data paths: `~/mnemosyne/raw/`, `~/mnemosyne/wiki/`, `~/mnemosyne/graph/knowledge.db`

## MCP Server

Mnemosyne provides an MCP server for AI agent integration:

```bash
# Start the MCP server
python -m mnemosyne.mcp

# Or via the CLI
mnemosyne mcp serve

# Install helper (prints config snippet for your MCP client)
mnemosyne mcp install --client claude-desktop
mnemosyne mcp install --client hermes
mnemosyne mcp install --client openclaw
```

**15 MCP tools** are available:
- **Read**: mnemosyne_search, mnemosyne_query, mnemosyne_get_entity, mnemosyne_list_entities, mnemosyne_stats, mnemosyne_wiki_status, mnemosyne_wiki_lint
- **Write**: mnemosyne_add, mnemosyne_extract, mnemosyne_update, mnemosyne_create_entity, mnemosyne_update_entity, mnemosyne_create_relation
- **Wiki maintenance**: mnemosyne_wiki_rebuild, mnemosyne_wiki_prune

**No-delete contract**: The MCP server never deletes data. `mnemosyne_update_entity` appends temporal versions (entity_history), and `mnemosyne_wiki_prune` only creates tombstone records.

**Transport**: Direct Python import (reuses KnowledgeGraph + Handlers in-process; no separate `mnemosyne serve` needed).

### `mnemosyne wiki` subcommands

| Subcommand | Description |
|------------|-------------|
| `status` | Read-only wiki health summary (counts, stale pages, contradiction totals) |
| `lint` | Check wiki links, metadata, and graph drift; use `--strict` to fail on warnings |
| `contradictions` | List graph-backed conflict review items with stable `conflict_id` values |
| `resolve <id>` | Update one conflict's resolution metadata without deleting evidence |
| `prune` | Plan stale wiki/graph reconciliation; `--apply-tombstones` writes tombstone records |
| `semantic-contradictions` | Opt-in local offline semantic contradiction discovery; `--write` persists results |
| `rebuild` | Regenerate generated wiki sections from graph data; `--dry-run` to preview |
| `doctor` | Run `status` and `lint` together |

All `wiki` write commands (`rebuild`, `add`, `update`) use a `.mnemosyne-wiki.lock` file per wiki root with a default 10-second timeout.

### LLM Wiki Maintenance

`mnemosyne add` and `mnemosyne update` can maintain a Karpathy-style LLM Wiki
alongside the structured knowledge graph:

```bash
# Default wiki root: ~/mnemosyne/wiki
mnemosyne add ./notes/meeting.md --domain daily

# Custom wiki root, useful for Obsidian/Joplin/git-backed vaults
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ./wiki

# Graph-only ingestion
mnemosyne add ./notes/meeting.md --domain daily --no-wiki

# Privacy-safe default: source excerpts are omitted.
# Opt in only when the raw source is safe to duplicate into Markdown.
mnemosyne add ./notes/meeting.md --domain daily --wiki-excerpts

# Inspect and repair the wiki layer
mnemosyne wiki status --wiki-root ./wiki --format json
mnemosyne wiki lint --wiki-root ./wiki --format json
mnemosyne wiki rebuild --wiki-root ./wiki --db-path ~/mnemosyne/graph/knowledge.db --dry-run
```

The maintained wiki has:

- `index.md` — content-oriented catalog of source and entity pages
- `log.md` — append-only ingest chronology
- `sources/<domain>/*.md` — source summary/provenance pages
- `entities/<type>/*.md` — accumulated entity pages with sources and relations

Generated pages include compact YAML frontmatter for provenance (`page_type`,
entity/source IDs, scope, channel, timestamps, and source hashes where
available). Generated sections are refreshed atomically between Mnemosyne
markers while manual notes outside those markers are preserved.

#### Conflict metadata and contradiction review

When ingestion sees an entity property conflict, Mnemosyne preserves the original
property value and records the incoming value under `properties["conflicts"]`.
The wiki promotes unresolved conflict metadata into a generated
`## Potential contradictions` section on entity pages.

- The section is deterministic and offline; it does not make semantic or LLM
  truth claims.
- Values are passed through the same redaction policy used for source excerpts.
- `mnemosyne wiki status --db-path ... --format json` includes contradiction
  totals and per-entity counts when the graph DB is available.
- `mnemosyne wiki lint --db-path ...` emits unresolved contradictions as
  warnings; add `--strict` when warnings should fail automation.
- `mnemosyne wiki contradictions --db-path ... --format json` lists review
  items with stable `conflict_id` values.
- `mnemosyne wiki resolve <conflict_id> --resolution accepted_existing`
  updates only review metadata (`resolution`, optional note/reviewer, review
  timestamp) and preserves the conflicting values plus source evidence. Use
  `--dry-run` first for automation.
- Resolution metadata is supported in stored conflict records:
  `unresolved`, `accepted_existing`, `accepted_incoming`, `superseded`, and
  `ambiguous`.

#### Optional semantic contradiction discovery

Semantic contradiction discovery is opt-in and separate from deterministic
conflict metadata. It produces review candidates, not truth judgments.

- `mnemosyne wiki semantic-contradictions --db-path ... --format json` runs
  the local offline heuristic detector without writing review files.
- Add `--write` to persist candidates under `review/semantic-contradictions.*`.
- Output uses the distinct `mnemosyne.semantic_contradiction_candidates.v1`
  schema, includes `processing_mode: local-offline`, and records that remote
  model calls are disabled.
- Candidate evidence includes source references, bounded redacted excerpts,
  confidence, rationale, generated-at metadata, and explicit uncertainty
  wording. Raw source excerpts require the explicit `--include-raw-excerpts`
  opt-in.
- `mnemosyne wiki status` and `mnemosyne wiki lint` report persisted semantic
  review candidates separately from deterministic property conflicts. Lint emits
  warnings only; use `--strict` if automation should fail on warnings.

#### Stale planning and tombstones

Mnemosyne treats stale wiki/graph lifecycle cleanup as review work, not an
automatic delete.

- `mnemosyne wiki prune --db-path ... --format json` produces a dry-run plan of
  stale candidates such as orphan entity/source pages and missing raw source
  paths.
- The plan includes candidate IDs, paths/entities/sources, reasons, risk labels,
  and manual-note previews when available.
- `mnemosyne wiki prune --apply-tombstones` writes Markdown tombstone records
  under `tombstones/` but still performs zero deletes.
- Tombstones include recovery metadata and manual note previews so users can
  archive or clean up deliberately.
- `mnemosyne wiki status` and `mnemosyne wiki lint` expose stale counts/warnings
  without failing by default.

#### Editor workflow: Joplin, Obsidian, or synced folders

Use an explicit `--wiki-root` when writing into an editor-controlled folder:

```bash
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ~/Notes/mnemosyne-wiki
mnemosyne wiki lint --wiki-root ~/Notes/mnemosyne-wiki
```

Editor contract:

- Open or import the wiki root as ordinary Markdown; no live editor dependency is required.
- In Joplin, use a folder/Markdown import workflow. Do not store Joplin API tokens in the repo or wiki; token automation is not required for this workflow.
- In Obsidian-style vaults, the generated `[[...]]` links are intended to remain portable. Some editors may render nested `[[path/to/page|label]]` links differently, so `mnemosyne wiki lint` remains the source of truth for broken-link checks.
- Treat text between `MNEMOSYNE:GENERATED` markers as rebuildable. Put human notes outside those markers, preferably under `## Notes`.
- Raw sources plus the graph database remain authoritative; editor pages are readable views plus manual notes.

#### Wiki writer locking

Wiki write commands use a single-writer lock file at
`<wiki-root>/.mnemosyne-wiki.lock` before refreshing generated pages. This
protects `mnemosyne add`, `mnemosyne update`, and `mnemosyne wiki rebuild` from
simultaneous writes to the same wiki root.

- Default write-lock timeout: 10 seconds.
- `mnemosyne wiki rebuild` accepts `--lock-timeout <seconds>` for controlled retries.
- `mnemosyne wiki status` and `mnemosyne wiki lint` remain read-only and do not lock by default.
- If a process crashes, inspect the JSON metadata in `.mnemosyne-wiki.lock`
  (`pid`, `hostname`, `created_at`, `action`, `wiki_root`) before manually
  removing it. Mnemosyne does not break stale locks automatically.
- Locking is intended for local filesystems; distributed/network filesystem
  semantics are not guaranteed.

The Markdown wiki is the readable, compounding artifact; SQLite + NetworkX remain
the queryable knowledge graph layer.

### Extraction Pipeline Options

```bash
python -m mnemosyne.extraction.pipeline \
  --domain coding \          # coding | daily | legal
  --source ~/path \          # File or directory
  --format json \            # json | wiki | summary
  --scope-id SESSION_ID \    # Attach scope to entities
  --source-channel CHANNEL \ # Tag extraction source
  --db-path ~/kg.db \        # Custom DB path
  --no-semantic \            # Skip semantic layer
  --incremental              # Skip unchanged files
```

### Deterministic Extraction (Zero LLM)

```bash
# Single file
python -m mnemosyne.extraction.deterministic.code_parser ~/project/main.py

# Directory with wiki output
python -m mnemosyne.extraction.deterministic.code_parser ~/project --format wiki

# With session scope
python -m mnemosyne.extraction.deterministic.code_parser ~/project \
  --scope-id impl-session --source-channel vscode
```

Supported languages: **Python, JavaScript, TypeScript, TSX, Go, Rust**

## Python API

### Entity Extraction

```python
from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
from pathlib import Path

extractor = TreeSitterExtractor()

# Extract from a single file
result = extractor.extract_file_full(Path("main.py"))
print(f"Found {len(result.entities)} entities")
print(f"Imports: {len(result.imports)}")
print(f"Calls: {len(result.calls)}")

# Extract from a directory
entities = extractor.extract_directory(Path("src/"), scope_id="my-session")

# Convert to wiki format
print(extractor.to_wiki_format(result.entities, result.imports, result.calls))
```

### Semantic Extraction

```python
from mnemosyne.extraction.semantic.slm_extractor import SemanticExtractor

with SemanticExtractor() as extractor:
    result = extractor.extract(
        "John Smith works at Google Inc",
        ["PERSON", "ORGANIZATION"],
        scope_id="session-1",
        source_channel="cli",
    )
    # result = {entities: [...], relations: [...], token_cost: N, extraction_method: "local_slm"}
```

### Knowledge Graph Queries

```python
from mnemosyne.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Statistics
stats = kg.get_stats()

# Search entities
results = kg.query("search:authenticate")

# Entity by type and name
results = kg.query("entity:function[parse_config]")

# Relations
results = kg.query("relation:calls")

# Shortest path between entities
results = kg.query("path:get_user,authenticate")

# Session-scoped queries
results = kg.query("entity:function[*]@session:impl-session")
```

### Scope Management

```python
from mnemosyne.graph.scope_manager import ScopeManager

sm = ScopeManager()

# Create hierarchical scopes
sm.create_scope("project-x", scope_type="project")
sm.create_scope("feature-auth", parent_id="project-x", scope_type="feature")
sm.create_scope("session-1", parent_id="feature-auth", scope_type="session")

# Query scope tree
children = sm.get_children("project-x")
lineage = sm.get_lineage("session-1")
```

## Domain Schemas

### Daily Life

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `task` | deadline, priority, status | Task management |
| `person` | role, contact, interaction history | Contact tracking |
| `place` | type, address, visit frequency | Location awareness |
| `event` | datetime, duration, participants | Calendar |
| `habit` | frequency, time, streak | Behavior tracking |
| `preference` | category, value, confidence | Personalization |
| `note` | title, content, tags | General notes |

### Coding

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `function` | signature, language, complexity | Code navigation |
| `class` | methods, attributes, inheritance | Architecture |
| `module` | exports, imports | Dependency tracking |
| `api` | endpoint, method, auth | API docs |
| `bug` | severity, status, affected functions | Bug tracking |
| `feature` | status, priority, implements | Feature tracking |
| `test` | type, coverage, status | QA |
| `dependency` | version, vulnerabilities | Supply chain |

### Legal

| Entity | Key Fields | Use Case |
|--------|-----------|----------|
| `statute` | jurisdiction, code, effective_date | Law reference |
| `clause` | obligation_type, content | Contract analysis |
| `case` | court, date, holding, reasoning | Precedent lookup |
| `party` | type, role, counsel | Party management |
| `obligation` | description, deadline | Compliance tracking |
| `deadline` | date, type, consequence | Deadline alerts |
| `contract` | parties, effective_date, status | Contract lifecycle |

## Wiki Link Syntax

| Syntax | Meaning |
|--------|---------|
| `[[note-name]]` | Link to a Joplin note |
| `[[entity:type:name]]` | Link to knowledge graph entity |
| `[[entity:type:name@session:s1]]` | Entity in specific session |
| `[[entity:type:name@project:p1@channel:code]]` | Entity with combined scope |
| `[[graph:query]]` | Embed graph query result |

## Directory Structure

```
mnemosyne-knowledge-graph/
├── mnemosyne/                    # Main Python package
│   ├── __init__.py               # Public API exports
│   ├── __main__.py               # python -m mnemosyne entry
│   ├── cli.py                    # Main CLI (query, extract)
│   ├── graph/                    # Knowledge graph engine
│   │   ├── cli.py                # Graph query CLI
│   │   ├── knowledge_graph.py    # SQLite + NetworkX
│   │   └── scope_manager.py      # Hierarchical scopes
│   ├── extraction/               # Extraction pipelines
│   │   ├── cli.py                # Extraction CLI
│   │   ├── pipeline.py           # 3-layer orchestration
│   │   ├── pipeline_types.py     # Type definitions
│   │   ├── deterministic/        # Zero-LLM layer
│   │   │   ├── code_parser.py    # Tree-sitter extraction
│   │   │   ├── types.py          # ParseResult, ImportEntity, CallRelation
│   │   │   └── languages/        # Per-language extractors
│   │   │       ├── base.py       # LanguageExtractor protocol
│   │   │       ├── python_extractor.py
│   │   │       ├── javascript_extractor.py
│   │   │       ├── go_extractor.py
│   │   │       └── rust_extractor.py
│   │   ├── semantic/             # Local SLM layer
│   │   │   └── slm_extractor.py  # GLiNER2 + REBEL
│   │   └── synthesis/            # Optional LLM layer
│   ├── raw/                      # Immutable source documents
│   ├── wiki/                     # LLM Wiki maintainer + extracted knowledge package
│   └── schema/                   # Domain schemas
├── tests/                        # 465 tests
├── joplin-plugin/                # Joplin plugin (TypeScript)
├── pyproject.toml                # PEP 621 config
├── CHANGELOG.md                  # Version history
└── MANUAL.md                     # Full user manual
```

## Performance Tuning

Mnemosyne features native write performance optimizations for scaling up your knowledge base.

### 1. SQLite Write-Ahead Logging (WAL) & Normal Sync
The sqlite database uses WAL journaling and relaxed synchronization to speed up database inserts and updates during raw source ingestion.
*   Concurrently reads and writes do not block each other.
*   Default SQLite connection `timeout` is raised to `30s` to prevent lock timeout failures.

### 2. Lock Offloading (MNEMOSYNE_LOCK_DIR)
Sequential write locks are processed safely. To prevent disk lock delays (especially on slower HDD or network volumes), redirect the lock path to `/tmp` (memory-backed `tmpfs` RAM disk):
```bash
export MNEMOSYNE_LOCK_DIR=/tmp
```

### 3. Native Rust Accelerator Core (mnemosyne-core)
Mnemosyne integrates a PyO3/Rayon based Rust extension module to speed up directory globbing and index page generation:
*   **Automatic Build**: Automatically built on package installs if `cargo` is present.
*   **Graceful Fallback**: If no Rust compiler is found, the system switches to the native Python logic seamlessly without errors.

Install the Rust toolchain (provides `cargo`) to enable the accelerator on a new machine:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```
Then reinstall the package so the build picks up `cargo`:
```bash
pip install --force-reinstall --no-deps "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
```

## Key Features

- **Zero API Cost**: Tree-sitter AST parsing (6 languages), local SLMs for NLP
- **Knowledge Compounding**: Wiki-layer accumulates knowledge across extractions
- **Temporal Tracking**: Entity version history with timestamps
- **Session Scopes**: Hierarchical project/topic/session scoping
- **FTS5 Fuzzy Search**: Ranked entity search via SQLite FTS5 BM25
- **Incremental Extraction**: SHA-256 content hash tracking
- **Multi-domain**: Coding, daily life, and legal schemas
- **Protocol-based**: `LanguageExtractor` protocol for extensible language support
- **Production Ready**: mypy strict, ruff clean, 626 tests, 81%+ coverage
