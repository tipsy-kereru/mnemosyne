# Mnemosyne Knowledge Graph - Manual

---

## 1. System Overview

### 1.1 What Is This?

A **local knowledge memory system for AI agents**. Based on Google Gemini's Universal Temporal Knowledge Graph research, it provides a **persistent knowledge compounding system** usable across daily life, coding, and legal domains.

**Core philosophy** (Andrej Karpathy):
> *"Obsidian is the IDE, the language model is the programmer, and the wiki is the codebase."*

### 1.2 Key Features

| Feature | Description |
|---------|-------------|
| **Zero API Cost** | Tree-sitter AST + local SLM — no external API dependency |
| **Knowledge Compounding** | Knowledge accumulates instead of re-exploring relationships from scratch |
| **Temporal Tracking** | Entity change history managed per version |
| **Session Scoping** | Hierarchical scope management: project / topic / session |
| **FTS5 Fuzzy Search** | Ranked entity search via SQLite FTS5 BM25 |
| **Obsidian Experience** | Joplin plugin with [[wiki-links]] support |
| **Production Grade** | 626 tests, mypy 0 errors, 81%+ coverage |

### 1.3 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RAW SOURCE (Immutable)                    │
│              mnemosyne/raw/{daily,coding,legal}/              │
│        Original documents are never modified - recompilable  │
└────────────────────────────┬────────────────────────────────┘
                             │ Extraction pipeline
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 WIKI LAYER (Knowledge Binary)                │
│              mnemosyne/wiki/{daily,coding,legal}/             │
│        Markdown + [[wiki-links]] - Human readable            │
└────────────────────────────┬────────────────────────────────┘
                             │ Schema governance
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 SCHEMA LAYER (CLAUDE.md)                     │
│              mnemosyne/schema/{domain}.md                    │
│        Graph structure changes via text file edits            │
└────────────────────────────┬────────────────────────────────┘
                             │ Graph database
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              KNOWLEDGE GRAPH (SQLite + NetworkX)             │
│              mnemosyne/graph/knowledge.db                    │
│        Temporal tracking, path finding, relation analysis    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Installation and Setup

Mnemosyne ships in two forms: a self-contained single binary (no Python
required) and a pip-installable package (Python 3.11+). Most end users want
the binary; contributors and pip-based users use the package form.

### 2.1 Binary Install (no Python required)

The `mnemosyne` CLI is published as a single PyOxidizer binary per platform,
attached to each [GitHub Release](https://github.com/tipsy-kereru/mnemosyne/releases).
CPython is embedded in the binary, so neither Python, pip, nor a virtualenv
is required on the host.

One-line installer:

```bash
# Linux + macOS (curl | sh)
curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh

# Windows (PowerShell 5.1+)
iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
```

Default install paths: `/usr/local/bin/mnemosyne` (Linux/macOS) or
`%LOCALAPPDATA%\Programs\mnemosyne\mnemosyne.exe` (Windows). Override with
`MNEMOSYNE_INSTALL_DIR`. The installer verifies SHA256 against
`SHA256SUMS.txt` before copying and refuses to overwrite an existing install
unless `--force` / `MNEMOSYNE_FORCE=1`.

| Platform       | Status      | Notes |
|----------------|-------------|-------|
| linux-x86_64   | GA          | Built on `ubuntu-latest`. |
| darwin-arm64   | GA          | Built on `macos-14`. Unsigned — see below. |
| windows-x86_64 | not shipped | PyOxidizer 0.24 `_socket` DLL load failure (ISSUE-0010). Use pip install (§2.2). |
| darwin-x86_64  | not shipped | Removed from matrix (slow build). Re-add when stable. |
| linux-aarch64  | not shipped | Cross-compile limitation. Needs native arm64 runner. |

**macOS unsigned binary:** binaries are not notarized (no Apple Developer
certificate yet). On first run Gatekeeper may report *"mnemosyne" cannot be
opened because the developer cannot be verified.* Strip the quarantine
attribute once:

```bash
xattr -d com.apple.quarantine /usr/local/bin/mnemosyne
```

**Windows unsigned binary:** SmartScreen may show an "unrecognized app"
warning. Click *More info → Run anyway*. Code-signing (Authenticode) is
deferred behind the same certificate gating as macOS notarization.

**Binary size:** the linux-x86_64 distribution is ~146 MB (binary plus
embedded `lib/` modules and filesystem-shipped `jsonschema_specifications`
/ `referencing` companions). This is above the 100 MB target; the
size-reduction lever is the PyOxidizer 0.4x + CPython 3.12 upgrade, tracked
as a follow-up. Do not move the binary without its companion directories,
or boot will fail with `No module named 'referencing._cores'`.

**Optional extensions (SLM / PDF):** the binary ships deterministic
extraction, the wiki layer, and the MCP server. Local SLM entity extraction
(GLiNER2) and PDF parsing are installed on demand as sidecar extensions so
the base binary stays small:

```bash
mnemosyne extension install slm     # GLiNER2 + torch (local SLM NER)
mnemosyne extension install pdf     # PyMuPDF long-document indexing
mnemosyne extension list
```

Extensions live under `${MNEMOSYNE_HOME:-~/.mnemosyne}/extensions/<name>/<version>/`,
are verified by per-file SHA256, and are loaded via `sys.path` injection at
startup.

**Signature verification (cosign keyless):** Linux and darwin binaries are
signed with cosign keyless (sigstore) on tag pushes. Verify a downloaded
binary:

```bash
cosign verify-blob \
  --certificate-identity-regexp 'https://github.com/tipsy-kereru/mnemosyne/.github/.+' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  --signature mnemosyne-linux-x86_64.sigstore \
  --bundle mnemosyne-linux-x86_64.sigstore \
  mnemosyne-linux-x86_64
```

Full binary-install reference (troubleshooting matrix, man pages, deferred
items): [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md).

### 2.2 pip Install (Python 3.11+)

For users who already run Python or want editable installs:

```bash
# Core only
pip install -e .

# With deterministic extraction (tree-sitter)
pip install -e ".[deterministic]"

# With semantic extraction (GLiNER2, torch)
pip install -e ".[semantic]"

# Development environment (lint, type-check, test)
pip install -e ".[dev]"

# Full installation
pip install -e ".[all]"
```

### 2.3 Joplin Plugin Installation

```bash
cd joplin-plugin/knowledge-graph
npm install && npm run build
npm run pack  # → creates knowledge-graph.jpl file

# Install in Joplin: Tools > Options > Plugins > "Install from file"
```

### 2.4 Uninstall

There is no single uninstaller. Remove each artifact manually — order does
not matter. Full reference: [docs/BINARY_INSTALL.md](docs/BINARY_INSTALL.md#uninstall).

```bash
# Binary (Linux/macOS)
sudo rm -f /usr/local/bin/mnemosyne
# Binary (Windows PowerShell)
#   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\mnemosyne"

# pip package
pip uninstall mnemosyne-kg

# Optional extensions
mnemosyne extension remove slm
mnemosyne extension remove pdf
# or all at once:
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}/extensions"

# Agent skill
rm -rf ~/.claude/skills/mnemosyne
rm -rf ~/.agents/skills/mnemosyne

# Data directory — KEEP to preserve graph.db / raw / wiki across reinstalls.
# Remove only for a fully clean slate:
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}"
```

Also strip any `MNEMOSYNE_*` environment variables from your shell rc.

---

## 3. CLI Usage

### 3.1 Basic Commands

| Command | Description |
|---------|-------------|
| `mnemosyne --version` | Show version |
| `mnemosyne query --stats` | Graph statistics |
| `mnemosyne query --query "search:term"` | FTS5 fuzzy search (ranked results) |
| `mnemosyne extract <path>` | Extract entities from file/directory |
| `mnemosyne add <target>` | Ingest file, directory, URL, or `--text` text into the graph |
| `mnemosyne update <path>` | Incrementally reflect changed files into graph and LLM Wiki |
| `mnemosyne wiki <subcommand>` | Inspect and manage Markdown LLM Wiki |
| `mnemosyne skill install` | Install agent skill for Claude Code or other agents |
| `mnemosyne mcp serve` | Start MCP server for AI agent integration |

### `mnemosyne add` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--text TEXT` | — | Ingest inline text instead of file/URL |
| `--domain {coding,daily,legal}` | `daily` | Ingest domain |
| `--scope-id ID` | — | Assign scope ID to ingested entities |
| `--source-channel CHANNEL` | `cli` | Ingest source channel tag |
| `--dry-run` | off | Preview extraction results without writing to graph |
| `--wiki-root PATH` | `~/mnemosyne/wiki` | LLM Wiki root directory |
| `--no-wiki` | off | Update knowledge graph only, skip wiki pages |
| `--wiki-excerpts` | off | Include bounded/redacted source excerpts in wiki pages (explicit opt-in) |

Default data paths: `~/mnemosyne/raw/`, `~/mnemosyne/wiki/`, `~/mnemosyne/graph/knowledge.db`

### `mnemosyne wiki` Subcommands

| Subcommand | Description |
|------------|-------------|
| `status` | Wiki status summary (page count, stale count, contradiction totals, etc.) |
| `lint` | Check wiki links, metadata, graph drift; use `--strict` to fail on warnings |
| `contradictions` | List graph-based conflict review items with stable `conflict_id` |
| `resolve <id>` | Update resolution metadata only, without deleting conflict evidence |
| `prune` | Preview stale wiki/graph cleanup plan; use `--apply-tombstones` to create tombstone records |
| `semantic-contradictions` | Local offline semantic contradiction detection (opt-in); use `--write` to save results |
| `rebuild` | Regenerate generated wiki sections from graph data; use `--dry-run` to preview |
| `doctor` | Run `status` and `lint` together |

`rebuild`, `mnemosyne add`, `mnemosyne update`, and other wiki-writing commands use a `.mnemosyne-wiki.lock` file per wiki root (default timeout: 10 seconds).

### 3.2 LLM Wiki + Knowledge Graph Ingest

`mnemosyne add` and `mnemosyne update` maintain a Karpathy-style Markdown LLM Wiki alongside the structured Knowledge Graph.

```bash
# Default wiki location: ~/mnemosyne/wiki
mnemosyne add ./notes/meeting.md --domain daily --scope-id meeting-demo

# Write wiki to a custom location (Obsidian/Joplin/git vault, etc.)
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ./wiki

# Update graph only, skip Markdown wiki
mnemosyne add ./notes/meeting.md --domain daily --no-wiki

# By default, source excerpts are not copied to wiki for safety
# Explicitly enable bounded/redacted excerpts only for trusted sources
mnemosyne add ./notes/meeting.md --domain daily --wiki-excerpts

# Wiki status check / lint / rebuild
mnemosyne wiki status --wiki-root ./wiki --format json
mnemosyne wiki lint --wiki-root ./wiki --format json
mnemosyne wiki rebuild --wiki-root ./wiki --db-path ~/mnemosyne/graph/knowledge.db --dry-run
```

Generated/updated structure:

```text
~/mnemosyne/wiki/
├── index.md              # Content-centric catalogue
├── log.md                # Append-only ingest log
├── sources/<domain>/     # Per-source summary/provenance pages
└── entities/<type>/      # Per-entity cumulative pages
```

The Markdown Wiki is a human-readable, LLM-maintainable presentation layer, while SQLite + NetworkX is the knowledge graph layer for path traversal and structured queries. Generated pages include YAML frontmatter for provenance; manual notes outside the Mnemosyne generated marker are preserved across updates/rebuilds.

#### Conflict Metadata and Contradiction Review

When property values for the same entity conflict during ingestion, Mnemosyne preserves the incoming value under `properties["conflicts"]` instead of overwriting the existing value. The Wiki surfaces unresolved conflict metadata in a generated `## Potential contradictions` section on entity pages for human review.

- This section is a deterministic/offline summary — not an LLM-based semantic judgment or "truth/falsehood" determination.
- Conflicting values are displayed after passing through the same redaction policy as source excerpts.
- `mnemosyne wiki status --db-path ... --format json` includes contradiction totals and per-entity counts when a graph DB is present.
- `mnemosyne wiki lint --db-path ...` reports unresolved contradictions as warnings. Use `--strict` to make warnings fail in automation.
- `mnemosyne wiki contradictions --db-path ... --format json` shows a list of review items with stable `conflict_id`.
- `mnemosyne wiki resolve <conflict_id> --resolution accepted_existing` updates only review metadata without deleting conflicting values or source evidence. Use `--dry-run` first in automation.
- Conflict records support resolution states: `unresolved`, `accepted_existing`, `accepted_incoming`, `superseded`, `ambiguous`.

#### Optional Semantic Contradiction Discovery

Semantic contradiction discovery is an opt-in review workflow separate from deterministic conflict metadata. Results are candidates for human review, not truth/falsehood determinations.

- `mnemosyne wiki semantic-contradictions --db-path ... --format json` runs the local offline heuristic detector but does not write a review file.
- Adding `--write` saves candidates under `review/semantic-contradictions.*`.
- Output uses a separate `mnemosyne.semantic_contradiction_candidates.v1` schema, explicitly stating `processing_mode: local-offline` and that remote models are disabled.
- Candidate evidence includes source reference, bounded/redacted excerpt, confidence, rationale, generated-at metadata, and uncertainty wording. Raw source excerpts are included only with `--include-raw-excerpts`.
- `mnemosyne wiki status` and `mnemosyne wiki lint` display persisted semantic review candidates separately from deterministic property conflicts. Lint emits warnings only; use `--strict` to fail in automation.

#### Stale Planning and Tombstones

Mnemosyne treats stale wiki/graph lifecycle cleanup as a review task, not automatic deletion.

- `mnemosyne wiki prune --db-path ... --format json` produces a dry-run plan of stale candidates (orphan entity/source pages, missing raw source paths, etc.).
- The plan includes candidate ID, path/entity/source, reason, risk label, and manual-note preview where available.
- `mnemosyne wiki prune --apply-tombstones` writes Markdown tombstone records under `tombstones/` but still performs zero deletions.
- Tombstones contain recovery metadata and manual note previews, allowing users to deliberately archive/cleanup.
- `mnemosyne wiki status` and `mnemosyne wiki lint` show stale counts/warnings but do not fail by default.

#### Writing to Joplin / Obsidian / Synced Folders

Specify `--wiki-root` when writing to an editor-managed folder.

```bash
mnemosyne add ./notes/meeting.md --domain daily --wiki-root ~/Notes/mnemosyne-wiki
mnemosyne wiki lint --wiki-root ~/Notes/mnemosyne-wiki
```

Usage contract:

- The wiki root can be opened or imported as a regular Markdown folder. No running Joplin instance is needed for CI or basic usage.
- In Joplin, use the Markdown/folder import approach. This workflow does not require a Joplin API token; do not store tokens in the repo or wiki.
- For Obsidian-style vaults, generated `[[...]]` links work as-is. However, editors may render `[[path/to/page|label]]` differently, so use `mnemosyne wiki lint` as the authority for broken link detection.
- Text between `MNEMOSYNE:GENERATED` markers will be replaced on rebuild. Write manual notes outside the markers, preferably under a `## Notes` section.
- Raw sources and the graph DB are the authoritative data; editor pages are the human-readable view + manual note layer.

#### Wiki Writer Lock

Commands that write to the wiki acquire a `<wiki-root>/.mnemosyne-wiki.lock` file per wiki root before updating generated pages. This lock prevents concurrent writes to the same wiki root from `mnemosyne add`, `mnemosyne update`, and `mnemosyne wiki rebuild`.

- Default timeout is 10 seconds.
- `mnemosyne wiki rebuild` accepts `--lock-timeout <seconds>` to adjust wait time.
- `mnemosyne wiki status` and `mnemosyne wiki lint` are read-only and generally do not acquire locks.
- If a process terminates abnormally and leaves a lock file, check the JSON metadata (`pid`, `hostname`, `created_at`, `action`, `wiki_root`) before manually deleting it. Mnemosyne does not automatically break stale locks.
- This lock is local-filesystem-based. Lock semantics on network/distributed filesystems are not guaranteed.

### 3.3 Extraction Pipeline

```bash
# Run full pipeline
python -m mnemosyne.extraction.pipeline \
  --domain coding \
  --source ~/my-project \
  --format json

# Session scope and incremental extraction
python -m mnemosyne.extraction.pipeline \
  --domain coding --source ~/my-project \
  --scope-id impl-session --source-channel vscode \
  --incremental

# Skip semantic extraction (deterministic parsing only)
python -m mnemosyne.extraction.pipeline \
  --domain coding --source ~/my-project --no-semantic
```

### 3.4 Deterministic Extraction (Zero LLM)

```bash
# Single file
python -m mnemosyne.extraction.deterministic.code_parser ~/project/main.py

# Entire directory
python -m mnemosyne.extraction.deterministic.code_parser ~/project --format wiki

# With session scope
python -m mnemosyne.extraction.deterministic.code_parser ~/project \
  --scope-id my-session --source-channel code
```

**Supported languages**: Python, JavaScript, TypeScript, TSX, Go, Rust

### 3.5 Semantic Extraction (Local SLM)

```bash
# Extract entities from text
python -m mnemosyne.extraction.semantic.slm_extractor \
  --text "John Smith works at Google" \
  --entities PERSON ORGANIZATION

# Extract from file
python -m mnemosyne.extraction.semantic.slm_extractor \
  --file ~/documents/meeting-notes.txt \
  --entities PERSON ORGANIZATION DATE
```

### 3.6 Graph Queries

```bash
# Statistics
python -m mnemosyne.graph.knowledge_graph --stats

# Entity lookup
python -m mnemosyne.graph.knowledge_graph --query "entity:function[parse_config]"

# Relation lookup
python -m mnemosyne.graph.knowledge_graph --query "relation:calls"

# Path finding
python -m mnemosyne.graph.knowledge_graph --query "path:get_user,authenticate"

# FTS5 fuzzy search (ranked results)
python -m mnemosyne.graph.knowledge_graph --query "search:authenticate"

# Session-scoped query
python -m mnemosyne.graph.knowledge_graph --query "entity:function[*]@session:impl-session"
```

### 3.7 MCP Server

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

---

## 4. Python API

### 4.1 Entity Extraction

```python
from mnemosyne.extraction.deterministic.code_parser import TreeSitterExtractor
from pathlib import Path

extractor = TreeSitterExtractor()

# Single file extraction
result = extractor.extract_file_full(Path("main.py"))
print(f"Entities: {len(result.entities)}")
print(f"Imports: {len(result.imports)}")
print(f"Calls: {len(result.calls)}")

# Directory extraction
entities = extractor.extract_directory(
    Path("src/"),
    scope_id="my-session"
)

# Wiki format conversion
print(extractor.to_wiki_format(result.entities, result.imports, result.calls))
```

### 4.2 Semantic Extraction

```python
from mnemosyne.extraction.semantic.slm_extractor import SemanticExtractor

# Automatic cleanup with context manager
with SemanticExtractor() as extractor:
    result = extractor.extract(
        "John Smith at Google Inc",
        ["PERSON", "ORGANIZATION"],
        scope_id="session-1",
        source_channel="cli",
    )
    # result = {entities: [...], relations: [...], token_cost: N}
```

### 4.3 Knowledge Graph Queries

```python
from mnemosyne.graph.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# Statistics
stats = kg.get_stats()

# FTS5 fuzzy search (ranked results)
results = kg.query("search:authenticate")

# Entity lookup
results = kg.query("entity:function[parse_config]")

# Relation lookup
results = kg.query("relation:calls")

# Shortest path
results = kg.query("path:get_user,authenticate")

# Session-scoped query
results = kg.query("entity:function[*]@session:impl-session")
```

### 4.4 Scope Management

```python
from mnemosyne.graph.scope_manager import ScopeManager

sm = ScopeManager()

# Create hierarchical scopes
sm.create_scope("project-x", scope_type="project")
sm.create_scope("feature-auth", parent_id="project-x", scope_type="feature")
sm.create_scope("session-1", parent_id="feature-auth", scope_type="session")

# Query scope tree
children = sm.get_children("project-x")
lineage = sm.get_lineage("session-1")  # session-1 → feature-auth → project-x
```

---

## 5. Domain Schemas

### 5.1 Daily Life

| Entity | Description | Key Attributes |
|--------|-------------|----------------|
| `task` | Action item / to-do | title, deadline, priority, status |
| `person` | Contact | name, role, contact, last_interaction |
| `place` | Location | name, type, address, visit_frequency |
| `event` | Calendar event / appointment | title, datetime, duration, participants |
| `habit` | Habit | name, frequency, time, streak |
| `preference` | Preference | category, value, confidence |
| `note` | General note | title, content, tags |

### 5.2 Coding

| Entity | Description | Key Attributes |
|--------|-------------|----------------|
| `function` | Function / method | name, signature, language, complexity |
| `class` | Class / struct | name, methods, attributes, inherits |
| `module` | Module / package | name, type, exports, imports |
| `api` | API endpoint | name, type, endpoint, method, auth_required |
| `bug` | Bug report | id, severity, status, affected_functions |
| `feature` | Feature request | id, status, priority |
| `test` | Test case | name, type, covers, status |
| `dependency` | External dependency | name, version, vulnerabilities |

### 5.3 Legal

| Entity | Description | Key Attributes |
|--------|-------------|----------------|
| `statute` | Law / regulation | name, jurisdiction, code, effective_date |
| `clause` | Clause | number, title, content, obligation_type |
| `case` | Court case | citation, court, date, holding, reasoning |
| `party` | Legal party | name, type, role, counsel |
| `obligation` | Obligation / requirement | description, obligated_party, deadline |
| `deadline` | Legal deadline | date, type, consequence |
| `contract` | Contract | title, parties, effective_date, status |

---

## 6. Wiki Link Syntax

| Syntax | Meaning | Example |
|--------|---------|---------|
| `[[note-name]]` | Joplin note link | `[[project-plan]]` |
| `[[entity:type:name]]` | Knowledge graph entity | `[[entity:function:authenticate]]` |
| `[[entity:type:name@session:s1]]` | Entity in specific session | `[[entity:function:parse@session:s1]]` |
| `[[entity:type:name@project:p1@channel:code]]` | Compound scope | - |
| `[[graph:query]]` | Graph query result | `[[graph:search:security]]` |

---

## 7. Directory Structure

```
mnemosyne-knowledge-graph/
├── mnemosyne/                    # Main Python package
│   ├── __init__.py               # Public API
│   ├── __main__.py               # python -m entry point
│   ├── cli.py                    # Main CLI (query, extract)
│   ├── graph/                    # Knowledge graph engine
│   │   ├── cli.py                # Graph query CLI
│   │   ├── knowledge_graph.py    # SQLite + NetworkX
│   │   └── scope_manager.py      # Hierarchical scopes
│   ├── extraction/               # Extraction pipeline
│   │   ├── cli.py                # Extraction CLI
│   │   ├── pipeline.py           # 3-layer orchestration
│   │   ├── pipeline_types.py     # Type definitions
│   │   ├── deterministic/        # Zero LLM layer
│   │   │   ├── code_parser.py    # Tree-sitter extraction
│   │   │   ├── types.py          # ParseResult, ImportEntity, CallRelation
│   │   │   └── languages/        # Language-specific extractors
│   │   │       ├── base.py       # LanguageExtractor protocol
│   │   │       ├── python_extractor.py
│   │   │       ├── javascript_extractor.py
│   │   │       ├── go_extractor.py
│   │   │       └── rust_extractor.py
│   │   ├── semantic/             # Local SLM layer
│   │   │   └── slm_extractor.py  # GLiNER2 + REBEL
│   │   └── synthesis/            # Optional LLM layer
│   ├── raw/                      # Immutable source documents
│   ├── wiki/                     # Extracted knowledge
│   └── schema/                   # Domain schemas
├── tests/                        # 465 tests
├── joplin-plugin/                # Joplin plugin (TypeScript)
├── pyproject.toml                # PEP 621 configuration
├── CHANGELOG.md                  # Version history
└── CLAUDE.md                     # System prompt
```

---

## 7. Performance Tuning

For large-scale wikis or environments with high concurrent writes, Mnemosyne provides several out-of-the-box optimization features.

### 7.1 Database Connection Tuning
The temporal knowledge graph uses SQLite for local state. The database engine is tuned as follows:
*   **WAL (Write-Ahead Logging) Mode**: Enabled by default, allowing concurrent readers and writers to access the database without locking conflicts.
*   **Synchronous Mode**: Set to `NORMAL`. This prevents expensive fsync flushes on every write, improving database throughput during bulk ingest operations.
*   **Timeout**: SQLite connection timeout is set to `30s` to resolve locking issues when multiple agents edit files concurrently.

### 7.2 Memory-Backed Lock Directory (Lock Offloading)
Mnemosyne's wiki module serializes write processes via a file-based lock. To avoid storage I/O delays, you can redirect lock files to a RAM disk (such as `/tmp` or another `tmpfs` path):
```bash
# Redirect lock files to RAM disk
export MNEMOSYNE_LOCK_DIR=/tmp
```
When configured, locks will be written in the specified fast-access storage path under deterministic hash names mapped to their wiki roots.

### 7.3 Hybrid Rust Acceleration Core (`mnemosyne-core`)
An optional PyO3-based Rust extension is integrated into the core package:
*   **Installation**: Automatically compiled during normal package installs if `cargo` is present.
*   **Offloading**: Offloads Python file globbing and index page generation to a parallel execution pool using `Rayon`.
*   **Fallback**: If no compiler is present, the package dynamically falls back to native Python indexing paths, preserving 100% feature parity.

---

## 8. Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: spacy` | `python -m spacy download en_core_web_sm` |
| GLiNER load failure | `pip install gliner` then retry |
| Missing tree-sitter grammar | Install language-specific package (e.g. `pip install tree-sitter-python`) |
| Joplin plugin won't load | Verify Joplin 2.14 or later |
| Empty graph query results | Try fuzzy search with `search:` |
| `mypy` errors | Run `pip install -e ".[dev]"` then `mypy mnemosyne/` |

---

## 9. Quality Metrics

| Metric | Current Status |
|--------|---------------|
| pytest | 626 passed |
| mypy | 0 errors (37+ source files) |
| ruff | 0 violations |
| Coverage | 81%+ |
| SPECs | 19 completed |

---

*Manual version: 3.1*
*Last updated: 2026-06-14*
