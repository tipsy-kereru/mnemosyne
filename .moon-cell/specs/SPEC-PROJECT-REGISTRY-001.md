# SPEC-PROJECT-REGISTRY-001: Project-Scoped Knowledge Graph with Hash-Based Registry

Generated: 2026-05-07 18:37:29 NZST
Status: implemented
Priority: high
Risk: medium
Source: User request — project-per-graph isolation with migration support

## 1. Problem Statement

Mnemosyne stores all entities in a single global `~/mnemosyne/graph/knowledge.db`. When running `mnemosyne add` from different project directories, entities from all projects mix together with no automatic separation. Users must manually pass `--scope-id <name>` to isolate data, which is error-prone and disconnected from actual project identity.

## 2. Goals

- Automatically detect the current project from the working directory
- Map each project to a unique hash-based ID stored in a registry table
- Scope all ingested entities/relations to the detected project
- Preserve existing data through additive migration (no destructive schema changes)
- Support cross-project queries for global knowledge discovery

## 3. Non-Goals

- Per-project separate SQLite database files (single DB, scoped rows)
- Multi-user or network-accessible project sharing
- Automatic project discovery outside the current working directory tree
- Changes to the wiki layer layout

## 4. Facts

- `entities` table has `scope_id TEXT DEFAULT NULL` column (already exists)
- `relations` table has `scope_id TEXT DEFAULT NULL` column (already exists)
- `scopes` table exists with `scope_type IN ('project', 'topic', 'session')` hierarchy
- 382 existing entities all have `scope_id = 'seal-spec'` (from mnemosyne-knowledge-graph project)
- `ingest_cache` tracks `file_path TEXT` and `content_hash TEXT` per ingested file
- Entity `properties` JSON may contain `source_file` key for origin tracking
- Current CLI accepts `--scope-id` as optional argument on `add` and `update`

## 5. Assumptions

- A "project" is identified by its root directory path (containing `.git/`, `.mnemosyne/`, or `pyproject.toml`/`package.json`)
- Users work in one project directory at a time (CWD-based detection)
- Hash-based project IDs provide stable, reproducible identification (SHA-256 of canonical path)
- Existing `scope_id` values remain valid and can be back-filled via migration

## 6. Requirements

### REQ-PR-001: Project Registry Table

Add a `projects` table to `knowledge.db`:

```sql
CREATE TABLE IF NOT EXISTS projects (
    project_hash TEXT PRIMARY KEY,   -- SHA-256 of canonical project root path
    project_name TEXT NOT NULL,       -- Human-readable name (from directory or config)
    project_path TEXT NOT NULL,       -- Absolute canonical path to project root
    scope_id TEXT REFERENCES scopes(id),
    domain TEXT NOT NULL DEFAULT 'coding',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'        -- JSON: description, tags, etc.
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_path ON projects(project_path);
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name);
```

### REQ-PR-002: Automatic Project Detection

Implement `detect_project()` function that:
1. Walks up from CWD looking for project root markers: `.git/`, `.mnemosyne/`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`
2. Canonicalizes the path (resolve symlinks, trailing slashes)
3. Returns `(project_path, project_hash)` or `None` if no project detected

### REQ-PR-003: Auto-Registration

When `mnemosyne add` or `mnemosyne update` runs:
1. Call `detect_project()` from CWD
2. If project found and not in `projects` table: auto-register
   - `project_hash` = SHA-256 of canonical path
   - `project_name` = directory basename
   - Create a `scopes` entry with `scope_type='project'` if none exists
   - Link `projects.scope_id` to the new scope
3. Use the project's `scope_id` for all ingested entities/relations
4. If `--scope-id` is explicitly provided, it overrides auto-detection

### REQ-PR-004: CLI Integration

Add `mnemosyne project` subcommand:
- `mnemosyne project list` — list all registered projects
- `mnemosyne project show [name|hash]` — show project details and entity counts
- `mnemosyne project register <path> [--name NAME]` — manually register a project
- `mnemosyne project unregister <name|hash>` — remove project registration (does not delete entities)
- `mnemosyne project migrate` — back-fill `projects` table from existing scope_id values

### REQ-PR-005: Migration Support

`mnemosyne project migrate` command:
1. Scan `entities` table for distinct `scope_id` values where `scope_id IS NOT NULL`
2. For each scope_id, check if a corresponding `projects` entry exists
3. If not, create one using scope_id as project_name and `NULL` as project_path (orphan scope)
4. Optionally prompt user to associate orphan scopes with project paths
5. Non-destructive: does not modify existing entity/relation data

### REQ-PR-006: Scope-Aware Queries

Extend `mnemosyne query` to support project context:
- When in a project directory, default queries to current project's scope
- `mnemosyne query --global` to search across all projects
- `mnemosyne query --project <name>` to query a specific project

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-PR-001 | `mnemosyne add file.py --domain coding` from a project directory auto-registers the project and scopes entities | Run from project dir, check `projects` and `scopes` tables |
| AC-PR-002 | `mnemosyne project list` shows all registered projects with entity counts | Register 2+ projects, verify output |
| AC-PR-003 | `mnemosyne project migrate` creates entries for existing scope_ids without data loss | Run on existing DB, verify 382 entities unchanged |
| AC-PR-004 | CWD detection correctly identifies project root from subdirectories | Run `mnemosyne add` from `src/` subdirectory |
| AC-PR-005 | `--scope-id` override still works when explicitly provided | Pass `--scope-id custom`, verify it takes precedence |
| AC-PR-006 | All existing 488 tests continue to pass | `pytest tests/` |
| AC-PR-007 | `mnemosyne query --project <name>` returns only entities from that project | Query after multi-project ingestion |

## 8. Risks

| ID | Risk | Mitigation |
|---|---|---|
| RK-PR-001 | Path canonicalization differences across OS | Use `Path.resolve()` consistently; normalize on write |
| RK-PR-002 | Breaking existing CLI behavior for users relying on global scope | Auto-detection only activates when project markers found; fallback to global |
| RK-PR-003 | Migration corrupts existing data | Migration is additive only; never modifies entity/relation rows |

## 9. Task Breakdown

| Task | Description | Dependencies |
|---|---|---|
| T1: Schema | Add `projects` table creation to `KnowledgeGraph._init_tables()` | None |
| T2: Detection | Implement `detect_project()` in new module `mnemosyne/graph/project.py` | None |
| T3: Auto-registration | Integrate project detection into `Ingester.add()` and `Ingester._add_file()` | T1, T2 |
| T4: CLI | Add `project` subcommand to `mnemosyne/cli.py` with list/show/register/unregister/migrate | T1, T2 |
| T5: Migration | Implement `migrate` handler that back-fills from existing scopes | T1, T4 |
| T6: Query | Extend `mnemosyne query` with `--project` and `--global` flags | T1, T2 |
| T7: Tests | Add `tests/test_project_registry.py` covering all AC items | T1-T6 |

## 10. Files to Create/Modify

| File | Action |
|---|---|
| `mnemosyne/graph/project.py` | NEW — project detection, registration, migration |
| `mnemosyne/graph/knowledge_graph.py` | MODIFY — add `projects` table in `_init_tables()`, add project query methods |
| `mnemosyne/cli.py` | MODIFY — add `project` subcommand, integrate auto-detection in add/update |
| `mnemosyne/ingest/ingester.py` | MODIFY — auto-scope entities with detected project scope_id |
| `tests/test_project_registry.py` | NEW — test suite for all acceptance criteria |
