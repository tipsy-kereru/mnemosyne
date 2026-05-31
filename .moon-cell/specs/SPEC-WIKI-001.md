---
id: SPEC-WIKI-001
version: "0.1.0"
status: completed
created: "2026-05-02 12:48:30 NZST"
updated: "2026-05-02 13:09:10 NZST"
author: Moon Cell Harness
priority: high
risk: medium
owner_role: Spec Architect
reviewer_role: Solution Architect / Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-001.md
related_backlog: "LLM-WIKI-HARDENING"
---

# SPEC-WIKI-001: LLM Wiki Hardening and Knowledge Graph Synchronization

Generated: 2026-05-02 12:48:30 NZST
Updated: 2026-05-02 13:09:10 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Harness style | Moon Cell controlled, SPEC-first lite, Karpathy guarded |
| Approval gate | G-SPEC satisfied by user request: `$moon-cell plan ... 스펙으로 작성` |
| Implementation gate | Completed by `$moon-cell run SPEC-WIKI-001` on 2026-05-02 |
| Target quality gate | QG-006: LLM Wiki / Graph Consistency |

## Problem Statement

The project now has a first LLM Wiki layer: `mnemosyne add/update` can maintain Markdown pages under a wiki root while also writing the structured SQLite + NetworkX knowledge graph. This confirms the project can operate as both an LLM Wiki and a knowledge graph.

The current implementation is intentionally minimal. It creates readable pages and basic provenance, but it does not yet provide the maintenance, repair, consistency, privacy, and lifecycle controls expected from a durable Karpathy-style LLM Wiki. Without hardening, the wiki can drift from the graph, stale pages can accumulate, source provenance can be incomplete, and sensitive source excerpts can be copied into Markdown unexpectedly.

## Current Evidence

| Evidence | Result | Source |
|---|---|---|
| LLM Wiki writer exists | `LLMWikiMaintainer` creates `index.md`, `log.md`, `sources/`, and `entities/` | `mnemosyne/wiki/llm_wiki.py` |
| Ingest integration exists | `Ingester` has `wiki_root`, writes `wiki_paths`, and skips wiki in dry-run | `mnemosyne/ingest/ingester.py` |
| CLI flags exist | `--wiki-root` and `--no-wiki` added for add/update paths | `mnemosyne/cli.py`, `mnemosyne/ingest/cli.py` |
| Tests exist | Wiki creation, source accumulation, manual notes preservation, ingest integration | `tests/test_llm_wiki.py`, `tests/test_ingest_cli.py` |
| Quality baseline | `444 passed`, ruff clean, mypy clean | 2026-05-02 local verification |

## Goals

| ID | Goal |
|---|---|
| G-001 | Make the Markdown LLM Wiki rebuildable, lintable, and repairable from durable source-of-truth data. |
| G-002 | Keep Knowledge Graph and LLM Wiki synchronized enough that either can be used safely for agent memory workflows. |
| G-003 | Preserve human-authored wiki notes while allowing generated sections to refresh deterministically. |
| G-004 | Improve provenance so pages can trace claims back to raw source, source page, scope, and graph entity/relation IDs. |
| G-005 | Add safety controls for excerpts and sensitive content copied from raw inputs into Markdown. |
| G-006 | Keep the implementation dependency-free unless a separate dependency decision SPEC explicitly approves otherwise. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-001 | Do not replace the SQLite + NetworkX knowledge graph with Markdown-only storage. |
| NG-002 | Do not require Obsidian, Joplin, or any specific editor to use the wiki. |
| NG-003 | Do not introduce remote LLM calls as a required path for wiki maintenance. |
| NG-004 | Do not redesign all extraction schemas in this SPEC. |
| NG-005 | Do not migrate existing user databases without an explicit migration plan and backup guidance. |

## Risk and Hardening Backlog

| ID | Area | Risk / Gap | Impact | Priority | Recommended Action |
|---|---|---|---|---|---|
| RISK-WIKI-001 | Rebuildability | No full `wiki rebuild` command from graph/raw data | Wiki drift cannot be repaired confidently | High | Add rebuild command that regenerates generated sections from graph/raw without deleting manual notes |
| RISK-WIKI-002 | Consistency | No `wiki lint` check for orphan pages, broken links, stale source pages, or graph/wiki count mismatch | Agents may trust stale or broken wiki context | High | Add lint report and CI-friendly nonzero exit behavior |
| RISK-WIKI-003 | Entity updates | Existing graph entities are skipped when already present; properties are not merged/versioned on ingest | Graph can remain stale while wiki receives newer references | High | Define update/merge policy for existing entities and relations |
| RISK-WIKI-004 | Deletion/pruning | Removed raw files only affect ingest cache; entity/wiki pruning is deferred | Old pages and graph facts can persist silently | High | Add prune plan with tombstones or stale markers before destructive delete |
| RISK-WIKI-005 | Provenance | Source pages and entity pages do not yet store stable source IDs, content hashes, or graph IDs in frontmatter | Harder to audit claims or rebuild deterministically | High | Add YAML frontmatter metadata contract |
| RISK-WIKI-006 | Privacy | Source excerpts are copied into Markdown by default when raw path is available | Sensitive raw text could be duplicated into wiki | High | Add excerpt policy: default limit, disable flag, redaction hook, and docs |
| RISK-WIKI-007 | Slug collisions | Entity/source filenames are label-based and can collide across scopes or IDs | Distinct entities can share a page accidentally | Medium | Use stable slug policy including type, normalized label, and short ID/hash disambiguator |
| RISK-WIKI-008 | URL provenance | URL ingest source page uses fetched raw path after fetch; original URL provenance can be weak in generated pages | Web source audit trail can be incomplete | Medium | Persist original URL in source metadata and wiki frontmatter |
| RISK-WIKI-009 | Atomic writes | Wiki pages are written directly, not via temp-file replace | Interrupted runs can leave partial Markdown | Medium | Add atomic write helper for generated wiki writes |
| RISK-WIKI-010 | Concurrent runs | Multiple ingest/update processes can write the same wiki pages concurrently | Race conditions and lost manual notes | Medium | Add file lock or documented single-writer guard |
| RISK-WIKI-011 | CLI surface | No dedicated `mnemosyne wiki` command group | Users lack clear status/rebuild/lint/doctor workflow | Medium | Add `mnemosyne wiki status|lint|rebuild|doctor` |
| RISK-WIKI-012 | Contradictions | No contradiction/stale-claim section or evidence confidence rollup | LLM Wiki can present conflicting facts flatly | Medium | Add conflict/staleness metadata and page sections |
| RISK-WIKI-013 | Scope semantics | Wiki links do not fully reflect scope visibility or parent/child scope resolution | Session-specific memories may appear global | Medium | Include scope-qualified links/frontmatter and lint checks |
| RISK-WIKI-014 | Test coverage | Current tests cover core writer behavior but not full CLI rebuild/lint/update scenarios | Regressions can slip through integration paths | Medium | Add integration tests with temp DB/raw/wiki roots |
| RISK-WIKI-015 | Performance | `index.md` scans all pages on every ingest | Large vaults may slow down | Low | Defer until page count warrants incremental index updates |
| RISK-WIKI-016 | Editor integration | Joplin/Obsidian integration is documented conceptually, not tested end-to-end | User experience may vary by editor | Low | Add docs and optional smoke tests for exported folder shape |

## Decisions Required

### DEC-WIKI-001: Source of Truth Policy

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| A | Raw sources + graph are authoritative; wiki generated sections are rebuildable views | Clear repair path; graph remains query engine | Requires rebuild/lint tooling | Recommended |
| B | Markdown wiki is authoritative; graph is derived from wiki | Human-editable source of truth | Harder to preserve structured graph semantics and extraction provenance | Defer |
| C | Raw sources only are authoritative; graph/wiki are disposable caches | Strong provenance | Loses curated wiki notes unless separately managed | Not recommended |

Decision: Use Option A for this SPEC.

### DEC-WIKI-002: Sensitive Excerpt Policy

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| A | Keep current bounded excerpt by default | More readable source pages | Copies sensitive source text into wiki | Not recommended as final policy |
| B | Disable excerpts by default; opt in with `--wiki-excerpts` | Safer default | Less immediately readable pages | Recommended |
| C | Keep excerpts but add redaction patterns first | Balanced | Requires robust redaction contract | Future enhancement after B |

Decision: Planned implementation should switch to Option B unless user chooses otherwise.

### DEC-WIKI-003: Existing Entity Merge Policy

| Option | Description | Pros | Cons | Recommendation |
|---|---|---|---|---|
| A | Skip existing entities forever | Simple | Stale graph data | Not acceptable for durable memory |
| B | Merge non-empty new properties and append history | Preserves continuity and updates facts | Requires conflict handling | Recommended |
| C | Replace entity properties wholesale | Simple updates | Can erase prior data and manual curation | Not recommended |

Decision: Use Option B with explicit conflict metadata.

## Requirements

### REQ-WIKI-001: Add Dedicated Wiki CLI Group

**EARS:** When a user needs to inspect or maintain the LLM Wiki, the system shall provide a dedicated `mnemosyne wiki` command group.

Acceptance criteria:

- `mnemosyne wiki --help` lists `status`, `lint`, `rebuild`, and `doctor` subcommands.
- Commands accept `--wiki-root`, `--db-path`, and relevant raw/source path options.
- Existing `mnemosyne add/update --wiki-root/--no-wiki` behavior remains backward compatible.

### REQ-WIKI-002: Implement Wiki Status

**EARS:** When a user runs `mnemosyne wiki status`, the system shall summarize wiki health without modifying files.

Acceptance criteria:

- Reports wiki root, page counts by category, last log entry timestamp, broken link count, and graph entity/relation counts when DB is available.
- Returns JSON with stable keys for automation.
- Does not create or modify wiki files.

### REQ-WIKI-003: Implement Wiki Lint

**EARS:** When a user runs `mnemosyne wiki lint`, the system shall detect wiki/graph consistency risks.

Acceptance criteria:

- Detects broken wiki links, orphan source pages, orphan entity pages, duplicate generated slugs, missing frontmatter, malformed generated blocks, and graph/wiki count mismatches.
- Supports `--strict` to return nonzero on warnings, not only errors.
- Emits both human-readable and JSON output options.

### REQ-WIKI-004: Implement Safe Wiki Rebuild

**EARS:** When a user runs `mnemosyne wiki rebuild`, the system shall regenerate generated wiki sections from durable data while preserving manual notes.

Acceptance criteria:

- Rebuild uses graph entities/relations plus raw/source metadata where available.
- Generated blocks are replaced; content outside generated blocks is preserved.
- `--dry-run` reports planned changes without writing files.
- Rebuild never deletes pages unless `--prune` and a separate confirmation/flag are provided.

### REQ-WIKI-005: Add Frontmatter Metadata Contract

**EARS:** When wiki pages are written, the system shall include stable machine-readable YAML frontmatter.

Acceptance criteria:

- Source pages include page type, domain, source ID, original source, raw path, content hash when available, scope ID, source channel, updated timestamp.
- Entity pages include page type, entity ID, entity type, label, scope ID, source channel, updated timestamp.
- Lint validates required frontmatter fields.
- Frontmatter remains compact and does not duplicate large properties.

### REQ-WIKI-006: Harden Entity and Relation Update Semantics

**EARS:** When ingestion encounters existing graph entities or relations, the system shall update them according to an explicit merge/version policy.

Acceptance criteria:

- Existing entities can receive new source references and non-conflicting properties.
- Conflicting property values are preserved in conflict metadata rather than silently overwritten.
- Entity history records update events.
- Duplicate relation IDs do not prevent confidence/source metadata from being refreshed when appropriate.

### REQ-WIKI-007: Add Safe Excerpt Controls

**EARS:** When source pages are generated, the system shall avoid copying raw content into wiki pages unless explicitly enabled or safely redacted.

Acceptance criteria:

- Default source pages omit raw excerpts or include only metadata plus a pointer to raw path.
- `--wiki-excerpts` or config enables bounded excerpts.
- Redaction pattern support exists for common secrets if excerpts are enabled.
- Tests verify excerpts are disabled by default and enabled only on request.

### REQ-WIKI-008: Add Stable Slug and Collision Policy

**EARS:** When multiple entities or sources normalize to the same slug, the system shall disambiguate pages deterministically.

Acceptance criteria:

- Slug policy is documented in code and README/manual.
- Colliding labels produce distinct paths, preferably with short stable IDs or hashes.
- Existing simple paths remain stable where no collision exists.
- Lint detects legacy collisions and reports repair suggestions.

### REQ-WIKI-009: Preserve Manual Notes and Generated Boundaries

**EARS:** When wiki generated sections refresh, the system shall preserve human-authored notes outside generated markers.

Acceptance criteria:

- Existing manual notes remain unchanged after ingest and rebuild.
- Malformed marker pairs are lint errors before rebuild writes.
- Tests cover notes before, after, and between generated blocks if supported.

### REQ-WIKI-010: Add Atomic Write Discipline

**EARS:** When wiki pages are written, the system shall write them atomically to reduce partial-file risk.

Acceptance criteria:

- Generated files are written via temp file + replace on the same filesystem.
- Failure leaves either the old file or the new file, not a truncated partial file.
- Tests or code review cover the helper behavior.

### REQ-WIKI-011: Add Integration Tests

**EARS:** When LLM Wiki maintenance features are changed, the test suite shall cover the end-to-end graph/wiki path.

Acceptance criteria:

- Tests use temporary DB/raw/wiki roots.
- Tests cover `add`, `update`, `wiki status`, `wiki lint`, and `wiki rebuild` happy paths.
- Tests cover dry-run, no-wiki, excerpt-disabled default, slug collision, and manual note preservation.
- Full suite, ruff, mypy pass.

### REQ-WIKI-012: Update Documentation and Harness Evidence

**EARS:** After implementation, user-facing docs and Moon Cell harness docs shall reflect the supported LLM Wiki workflow and its risks.

Acceptance criteria:

- README and Korean manual document `mnemosyne wiki` commands and safe excerpt policy.
- `.moon-cell/docs/harness/QUALITY_GATES.md` includes QG-006.
- `.moon-cell/docs/harness/TASK_ROUTING.md`, `MANIFEST.md`, `CHANGELOG.md`, and `CONTEXT_HANDOFF.md` are refreshed.

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Requirements | Verification |
|---|---|---|---|---|
| WIKI-T1 | Spec Architect | Confirm source-of-truth, excerpt, merge, and slug policies | DEC-WIKI-001..003, REQ-WIKI-005..008 | SPEC decision table updated if changed |
| WIKI-T2 | Test Architect | Add failing/targeted tests for status/lint/rebuild and safety policies | REQ-WIKI-001..011 | Targeted tests fail before implementation where feasible |
| WIKI-T3 | Implementer | Add frontmatter, stable metadata, and atomic write helper | REQ-WIKI-005, REQ-WIKI-010 | Unit tests pass |
| WIKI-T4 | Implementer | Add entity/relation merge and history update semantics | REQ-WIKI-006 | Graph tests and history assertions pass |
| WIKI-T5 | Implementer | Add `mnemosyne wiki status` and `lint` | REQ-WIKI-001..003 | CLI tests pass; JSON contract snapshots pass |
| WIKI-T6 | Implementer | Add safe `wiki rebuild` preserving manual notes | REQ-WIKI-004, REQ-WIKI-009 | Rebuild tests pass with manual notes preserved |
| WIKI-T7 | Security Reviewer | Review excerpt/redaction defaults and path handling | REQ-WIKI-007, REQ-WIKI-008 | Security checklist has no blocking findings |
| WIKI-T8 | Writer | Update README/manual and harness docs | REQ-WIKI-012 | Docs mention safe defaults and command examples |
| WIKI-T9 | Reviewer | Run final diff and quality gates | All | Full verification evidence recorded |

## Implementation Plan

1. Baseline current behavior with targeted tests and full quality suite.
2. Add tests for frontmatter, disabled excerpts, collision handling, and manual note preservation.
3. Add small internal wiki metadata and atomic-write helpers.
4. Update graph storage merge semantics with conservative conflict preservation.
5. Add `mnemosyne wiki status` read-only command.
6. Add `mnemosyne wiki lint` read-only command.
7. Add `mnemosyne wiki rebuild --dry-run` first, then write mode preserving notes.
8. Add docs and Moon Cell QG-006.
9. Run full quality verification and update harness evidence.

## Verification Commands

Minimum implementation verification:

```bash
python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q
python -m pytest --tb=short -q
ruff check mnemosyne tests
mypy mnemosyne
git diff --check
```

Recommended CLI smoke checks with temporary roots:

```bash
mnemosyne-add --text "Alice works on Mnemosyne" --domain daily --db-path /tmp/mnemosyne.db --wiki-root /tmp/mnemosyne-wiki
mnemosyne wiki status --wiki-root /tmp/mnemosyne-wiki --db-path /tmp/mnemosyne.db --format json
mnemosyne wiki lint --wiki-root /tmp/mnemosyne-wiki --format json
mnemosyne wiki rebuild --wiki-root /tmp/mnemosyne-wiki --db-path /tmp/mnemosyne.db --dry-run
```

Note: Smoke commands must be adjusted to use a controlled test DB/raw/wiki root; do not write to production user vaults during automated tests.

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-WIKI-001 | Full tests | Pass |
| DOD-WIKI-002 | Lint/type | ruff and mypy pass |
| DOD-WIKI-003 | Wiki status | Reports stable page/graph health JSON without writes |
| DOD-WIKI-004 | Wiki lint | Detects broken links, stale/missing metadata, and collisions |
| DOD-WIKI-005 | Wiki rebuild | Regenerates generated sections while preserving manual notes |
| DOD-WIKI-006 | Provenance | Source/entity pages include required frontmatter |
| DOD-WIKI-007 | Safety | Excerpts disabled by default or safely redacted when enabled |
| DOD-WIKI-008 | Graph sync | Existing entity/relation updates have explicit merge/history behavior |
| DOD-WIKI-009 | Docs | README/manual describe LLM Wiki + graph workflow and safe defaults |
| DOD-WIKI-010 | Harness | QG-006, changelog, task routing, manifest, and handoff updated |

## Open Questions

| ID | Question | Default |
|---|---|---|
| OQ-WIKI-001 | Should the wiki default root remain `~/mnemosyne/wiki` or become opt-in to avoid surprise file writes? | Keep current default for now, but document clearly |
| OQ-WIKI-002 | Should source excerpts be disabled immediately in a small patch before the full SPEC? | Yes if privacy risk is prioritized |
| OQ-WIKI-003 | Should graph entity merge semantics be implemented before wiki rebuild? | Yes; rebuild quality depends on graph freshness |
| OQ-WIKI-004 | Should Joplin plugin integration be part of this SPEC? | No; track separately unless editor workflow becomes priority |

## Deferred Follow-Up Candidates

| ID | Candidate | Reason for Deferral |
|---|---|---|
| FUTURE-WIKI-001 | Joplin/Obsidian export polish and smoke testing | Editor-specific UX, lower core risk |
| FUTURE-WIKI-002 | Contradiction detection with LLM summarization | Requires broader extraction/conflict design |
| FUTURE-WIKI-003 | Incremental index optimization for very large vaults | Performance need not proven yet |
| FUTURE-WIKI-004 | Concurrent writer file locking | Important for multi-process usage, but atomic writes reduce first-order risk |


## Implementation Result

Completed: 2026-05-02 13:09:10 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-001 | PASS | Added `mnemosyne wiki status|lint|rebuild|doctor` via `mnemosyne/wiki/cli.py` and top-level CLI routing |
| REQ-WIKI-002 | PASS | `LLMWikiMaintainer.status()` reports page counts, broken links, log state, and graph stats |
| REQ-WIKI-003 | PASS | `LLMWikiMaintainer.lint()` detects broken links, missing frontmatter, malformed generated blocks, identity duplicates, and graph/wiki count drift |
| REQ-WIKI-004 | PASS | `rebuild_from_graph()` regenerates generated sections from graph rows and preserves manual notes; dry-run returns planned paths |
| REQ-WIKI-005 | PASS | Source/entity/index/log pages now include compact YAML frontmatter |
| REQ-WIKI-006 | PASS | Existing entities merge non-conflicting source metadata, preserve conflicts, and append entity history; relation metadata can refresh |
| REQ-WIKI-007 | PASS | Source excerpts are omitted by default; `--wiki-excerpts` opts into bounded redacted excerpts |
| REQ-WIKI-008 | PASS | Page path disambiguation appends a stable short hash when an existing page has a different entity/source identity |
| REQ-WIKI-009 | PASS | Generated marker replacement preserves manual notes outside generated sections |
| REQ-WIKI-010 | PASS | Wiki generated writes use temp-file plus `os.replace()` atomic writes |
| REQ-WIKI-011 | PASS | Added unit/integration coverage for wiki CLI, rebuild, lint/status, safe excerpts, merge history, and top-level help |
| REQ-WIKI-012 | PASS | README, Korean manual, and Moon Cell harness evidence refreshed |

Verification evidence:

```text
pytest -q
450 passed in 9.24s

ruff check mnemosyne tests
All checks passed!

mypy mnemosyne
Success: no issues found in 37 source files

git diff --check
(no output)
```
