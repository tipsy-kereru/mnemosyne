---
name: mnemosyne
description: "knowledge graph memory for AI agents — ingest docs/code/URLs, query entities/relations, manage wiki, extract code entities, manage projects and hooks via mnemosyne CLI"
trigger: /mnemosyne
---

# /mnemosyne

Persistent knowledge graph memory for AI agents. Ingest files, URLs, and text into a local knowledge graph, query entities and relations, extract code structure, manage project scopes, and maintain a Markdown wiki.

## Usage

```
/mnemosyne                                                # show graph stats
/mnemosyne add <file_or_url>                              # ingest into knowledge graph (auto-scopes to project)
/mnemosyne add <file_or_url> --domain coding              # domain-specific ingestion
/mnemosyne add <file_or_url> --domain daily --scope-id s1 # scoped ingestion (overrides auto-scope)
/mnemosyne add --text "Alice works at Acme Corp"          # inline text ingestion
/mnemosyne query "search:term"                            # fuzzy search entities (scoped to current project)
/mnemosyne query "search:term" --global                   # search across all projects
/mnemosyne query "entity:function[parse]"                 # entity by type and name
/mnemosyne query "entity:function[*]" --project myapp     # query a specific project
/mnemosyne query "relation:calls"                         # relation lookup
/mnemosyne query "path:auth,db"                           # shortest path between entities
/mnemosyne query --stats                                  # graph statistics
/mnemosyne extract <path>                                 # extract code entities (zero LLM)
/mnemosyne extract <path> --domain coding --format json   # structured extraction
/mnemosyne project list                                   # list all registered projects
/mnemosyne project show                                   # show current project details
/mnemosyne project show <name>                            # show a specific project
/mnemosyne project register <path>                        # manually register a project
/mnemosyne project migrate                                # back-fill projects from existing scopes
/mnemosyne hook install git                               # install git post-commit hook
/mnemosyne hook install claude                            # install Claude Code hook
/mnemosyne hook install all                               # install hooks for all platforms
/mnemosyne hook status                                    # show hook status
/mnemosyne wiki status                                    # wiki health check
/mnemosyne wiki lint                                      # check wiki integrity
/mnemosyne wiki rebuild                                   # regenerate wiki from graph
/mnemosyne wiki doctor                                    # status + lint combined
/mnemosyne update <path>                                  # incremental update from changed files
```

## What mnemosyne is for

mnemosyne provides persistent, compounding knowledge memory that survives across sessions. Instead of re-reading everything each time, the agent stores entities and relations in a local SQLite + NetworkX graph and a Markdown wiki.

Three things it does that an agent alone cannot:
1. **Persistent memory** — entities and relations stored in `~/mnemosyne/graph/knowledge.db` survive across sessions. Query them weeks later without re-reading source files.
2. **Cross-domain linking** — connect daily life (tasks, people), coding (functions, classes), and legal (statutes, contracts) entities in one graph.
3. **Knowledge compounding** — each ingestion adds to the graph. Wiki pages accumulate knowledge. Temporal versioning tracks entity changes over time.

Use it for:
- Project knowledge management (who works on what, which functions call which)
- Personal memory (tasks, contacts, habits, events)
- Code navigation (call graphs, import graphs, dependency tracking)
- Legal document analysis (statutes, clauses, deadlines, parties)

## What You Must Do When Invoked

Parse the subcommand from the user's input. If no subcommand is given, default to showing graph stats.

### Step 1 — Ensure mnemosyne is installed

```bash
# Detect mnemosyne CLI
MNEMOSYNE_BIN=$(which mnemosyne 2>/dev/null)
if [ -z "$MNEMOSYNE_BIN" ]; then
    echo "mnemosyne CLI not found. Installing..."
    pip install "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git" 2>&1 | tail -3
    MNEMOSYNE_BIN=$(which mnemosyne 2>/dev/null)
fi
if [ -z "$MNEMOSYNE_BIN" ]; then
    echo "ERROR: Could not install mnemosyne. Install manually:"
    echo "  pip install 'mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git'"
    exit 1
fi
mnemosyne --version
```

### Step 2 — Route to subcommand

Based on the user's input, execute the appropriate subcommand below.

---

## Subcommand: `add` (Ingest)

Ingest a file, directory, URL, or inline text into the knowledge graph. Entities are automatically scoped to the detected project (based on `.git/`, `pyproject.toml`, etc. in the directory tree).

```bash
# File or directory (auto-scoped to current project)
mnemosyne add <path> --domain <daily|coding|legal> [--source-channel CHANNEL]

# Explicit scope override (bypasses auto-detection)
mnemosyne add <path> --domain <daily|coding|legal> --scope-id ID

# URL (fetched and extracted)
mnemosyne add <url> --domain <daily|coding|legal>

# Inline text
mnemosyne add --text "text content" --domain <daily|coding|legal>

# Dry run (preview without writing)
mnemosyne add <path> --domain coding --dry-run

# With wiki output
mnemosyne add <path> --domain daily --wiki-root ./wiki

# Graph only, skip wiki
mnemosyne add <path> --domain daily --no-wiki
```

**Domain selection guide:**
- `daily` — meeting notes, tasks, contacts, events, habits, personal notes
- `coding` — source code, API docs, bug reports, feature specs, test files
- `legal` — contracts, statutes, case law, regulatory documents, compliance

**After ingestion**, report:
- Number of entities extracted and added
- Number of relations found
- Any errors or warnings

---

## Subcommand: `query` (Graph Query)

Query the knowledge graph for entities, relations, and paths. Queries are automatically scoped to the current project. Use `--global` to search across all projects or `--project <name>` to target a specific one.

```bash
# Graph statistics
mnemosyne query --stats

# Fuzzy search (scoped to current project)
mnemosyne query --query "search:<term>"

# Search across all projects
mnemosyne query --query "search:<term>" --global

# Query a specific project
mnemosyne query --query "entity:<type>[*]" --project <name>

# Entity by type and name
mnemosyne query --query "entity:<type>[<name>]"

# All entities of a type
mnemosyne query --query "entity:<type>[*]"

# Relations by type
mnemosyne query --query "relation:<relation_type>"

# Shortest path between two entities
mnemosyne query --query "path:<entity1>,<entity2>"

# Session-scoped query
mnemosyne query --query "entity:function[*]@session:<session_id>"
```

**After query**, present results in a readable format:
- Entity queries: list entities with type, name, key properties
- Relation queries: list source → relation → target triples
- Path queries: show the path as a chain with relation types
- Search: rank results by relevance, show type and name

---

## Subcommand: `extract` (Code Extraction)

Extract entities from source code using deterministic tree-sitter parsing (zero LLM cost).

```bash
# Single file
mnemosyne extract <file_path>

# Entire directory
mnemosyne extract <directory> --domain coding --format json

# With session scope
mnemosyne extract <directory> --scope-id <session_id> --source-channel <channel>
```

**Supported languages:** Python, JavaScript, TypeScript, TSX, Go, Rust

**Extracted entities:**
- Functions (name, signature, language, complexity)
- Classes (name, methods, attributes, inheritance)
- Imports (module dependency graph)
- Calls (function call graph)

**After extraction**, summarize:
- Number of files processed
- Functions, classes, imports, calls found
- Any language-specific notes

---

## Subcommand: `wiki` (Wiki Management)

Manage the Markdown wiki layer.

```bash
# Health check
mnemosyne wiki status [--wiki-root PATH] [--format json]

# Integrity check
mnemosyne wiki lint [--wiki-root PATH] [--strict]

# Regenerate wiki from graph
mnemosyne wiki rebuild [--wiki-root PATH] [--db-path PATH] [--dry-run]

# Combined check
mnemosyne wiki doctor [--wiki-root PATH]

# Check contradictions
mnemosyne wiki contradictions [--db-path PATH] [--format json]

# Plan stale cleanup
mnemosyne wiki prune [--db-path PATH] [--format json]
```

**After wiki operations**, report:
- Page count, stale count, contradiction count
- Any broken links or drift detected
- Actions taken (if rebuild/prune)

---

## Subcommand: `update` (Incremental Update)

Incrementally update the graph and wiki from changed files.

```bash
mnemosyne update <path> [--domain <domain>] [--wiki-root PATH]
```

Only re-processes files whose content hash has changed since the last ingestion.

---

## Subcommand: `project` (Project Management)

Manage project-scoped knowledge graphs. Each project is identified by a hash of its root directory path and maps to a scope in the knowledge graph.

```bash
# List all registered projects with entity counts
mnemosyne project list

# Show current project details (auto-detected from CWD)
mnemosyne project show

# Show a specific project by name or hash
mnemosyne project show <name_or_hash>

# Manually register a project
mnemosyne project register <path> [--name NAME]

# Remove project registration (entities preserved)
mnemosyne project unregister <name_or_hash>

# Back-fill projects table from existing scope_id values
mnemosyne project migrate
```

**Auto-detection**: When running `mnemosyne add` or `mnemosyne query` from a project directory (containing `.git/`, `pyproject.toml`, `package.json`, etc.), entities are automatically scoped to that project. Override with `--scope-id`.

**After `project list`**, present a table of projects with their entity counts and paths.

---

## Subcommand: `hook` (Hook Management)

Install, remove, or check hooks that auto-sync the knowledge graph on file changes. Supports: git, Claude Code, Codex CLI, Gemini CLI, Copilot CLI.

```bash
# Install default hooks (git + claude)
mnemosyne hook install

# Install for a specific platform
mnemosyne hook install git
mnemosyne hook install claude
mnemosyne hook install codex
mnemosyne hook install gemini
mnemosyne hook install copilot

# Install for all platforms
mnemosyne hook install all

# Overwrite existing hooks
mnemosyne hook install git --force

# Remove hooks
mnemosyne hook remove git
mnemosyne hook remove --all

# Check installed status
mnemosyne hook status
```

**Platform details:**
- `git`: post-commit hook that runs `mnemosyne update` after each commit
- `claude`: PostToolUse hook in `.claude/settings.json` that runs `mnemosyne add` on file writes
- `codex`: PostToolUse hook for Codex CLI
- `gemini`: AfterTool hook for Gemini CLI
- `copilot`: postToolUse hook for GitHub Copilot CLI

---

## Subcommand: default (no args) — Show Stats

```bash
mnemosyne query --stats
```

Present the output as a summary: total entities by type, total relations, graph size, last update time.

---

## Important Notes

1. **Data paths**: Default data locations are `~/mnemosyne/raw/`, `~/mnemosyne/wiki/`, `~/mnemosyne/graph/knowledge.db`
2. **Domain matters**: Always specify `--domain` for best extraction results. Auto-detection is available but explicit is better.
3. **Project scoping**: Entities are automatically scoped to the detected project. Use `--scope-id` to override, or `--global` on queries to search across all projects.
4. **Project registry**: Projects are auto-registered on first `add` from a project directory. Use `mnemosyne project list` to see all projects.
5. **Idempotent ingestion**: Re-ingesting the same file updates entities in place; it does not create duplicates.
6. **Cost**: Deterministic extraction (tree-sitter) is free. LLM-based synthesis is optional and only triggered when semantic understanding is needed.
7. **Wiki is optional**: Use `--no-wiki` for graph-only workflows. The wiki is a human-readable presentation layer.
8. **Conflict handling**: When entity properties conflict between ingestions, both values are preserved. Use `mnemosyne wiki contradictions` to review.
9. **Hooks**: Use `mnemosyne hook install` to auto-sync the graph on file changes or git commits. Supports git, Claude Code, Codex, Gemini, and Copilot.
