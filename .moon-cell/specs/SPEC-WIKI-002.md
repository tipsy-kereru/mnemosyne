---
id: SPEC-WIKI-002
version: "0.1.0"
status: completed
created: "2026-05-02 13:19:03 NZST"
updated: "2026-05-02 21:55:38 NZST"
author: Moon Cell Harness
priority: medium
risk: medium
owner_role: Spec Architect / UX Writer
reviewer_role: Solution Architect / QA
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-002.md
related_backlog: "FUTURE-004"
---

# SPEC-WIKI-002: Joplin / Editor UX Polish for LLM Wiki

Generated: 2026-05-02 13:19:03 NZST
Updated: 2026-05-02 21:55:38 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-002.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Parent work | SPEC-WIKI-001 completed core LLM Wiki hardening |
| Target gate | QG-006 plus editor smoke evidence |
| Implementation completed | 2026-05-02 21:55:38 NZST |

## Problem Statement

SPEC-WIKI-001 made the Markdown LLM Wiki durable, rebuildable, lintable, and graph-backed. The current UX is intentionally editor-neutral. Users who want to browse or maintain the wiki through Joplin, Obsidian, or a synced folder still need clearer import/export guidance, stable folder conventions, and smoke-tested workflows.

Without editor polish, the wiki can be technically correct but awkward to use: pages may import with weak navigation, generated sections may look unsafe to edit, and users may not know which notes are source-of-truth versus generated views.

## Goals

| ID | Goal |
|---|---|
| G-WIKI-002-001 | Make the generated wiki folder usable in Joplin-style and Obsidian-style Markdown workflows without changing the graph source-of-truth policy. |
| G-WIKI-002-002 | Clearly mark generated sections, manual note zones, raw-source pointers, and rebuild behavior for humans. |
| G-WIKI-002-003 | Provide a low-risk smoke test or fixture that validates the exported folder shape and link conventions. |
| G-WIKI-002-004 | Keep editor integration optional; no mandatory Joplin/Obsidian runtime dependency. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-WIKI-002-001 | Do not require a running Joplin server or token for normal tests. |
| NG-WIKI-002-002 | Do not turn Markdown pages into the canonical source of truth. |
| NG-WIKI-002-003 | Do not implement bidirectional editor sync in this SPEC unless explicitly expanded. |
| NG-WIKI-002-004 | Do not store secrets, Joplin tokens, or editor profiles in the repo or wiki. |

## Current Evidence

| Evidence | Result | Source |
|---|---|---|
| Editor-neutral wiki exists | `index.md`, `log.md`, `sources/`, and `entities/` | `mnemosyne/wiki/llm_wiki.py` |
| Manual notes preserved | Generated block replacement keeps content outside markers | SPEC-WIKI-001 |
| Link style exists | Wiki uses `[[...]]` links | `mnemosyne/wiki/llm_wiki.py` |
| Docs mention wiki commands | README and Korean manual updated | SPEC-WIKI-001 |

## Requirements

### REQ-WIKI-002-001: Editor-Oriented Folder Contract

**EARS:** When users open or import the wiki folder in a Markdown editor, the folder structure shall be predictable and documented.

Acceptance criteria:
- Document `index.md`, `log.md`, `sources/<domain>/`, and `entities/<type>/` as stable top-level conventions.
- Add an editor usage section for Joplin and Obsidian-style workflows.
- State that raw sources and graph DB remain authoritative; editor pages are generated views plus manual notes.

### REQ-WIKI-002-002: Human-Safe Generated Section Labels

**EARS:** When generated wiki pages are opened by humans, generated sections shall explain what can and cannot be safely edited.

Acceptance criteria:
- Generated block headers include concise edit guidance.
- Manual note areas are documented as safe zones outside generated markers.
- Rebuild/lint behavior explicitly states manual note preservation and generated block replacement.

### REQ-WIKI-002-003: Joplin Import Guidance

**EARS:** When a user wants to use Joplin, the docs shall provide a safe import/export path that does not require credentials.

Acceptance criteria:
- Provide a folder-import workflow using generated Markdown files.
- Provide a warning that Joplin API/token automation is not required and should not be stored in the repo.
- Include expected caveats around wiki-link rendering if Joplin does not resolve every `[[link]]` form identically.

### REQ-WIKI-002-004: Optional Editor Smoke Fixture

**EARS:** When editor UX changes are made, tests or fixtures shall verify the wiki folder remains editor-friendly.

Acceptance criteria:
- A temp wiki fixture contains index, source, entity, and log pages.
- Smoke validation checks relative paths, frontmatter, generated markers, and wiki links.
- No live editor dependency is required for CI.

### REQ-WIKI-002-005: CLI Discoverability

**EARS:** When users inspect wiki commands, the CLI help shall point to editor-safe workflows.

Acceptance criteria:
- `mnemosyne wiki --help` or docs near the command mention editor-neutral generated Markdown.
- README/manual examples include `--wiki-root` pointing to a user-controlled folder.
- Do not surprise-write into editor vaults without explicit `--wiki-root` in examples.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-002-001 | Joplin and Obsidian resolve wiki links differently | Broken navigation in one editor | Document known caveats; keep Markdown generic |
| R-WIKI-002-002 | Users edit generated blocks | Manual edits lost on rebuild | Clear markers and safe edit guidance |
| R-WIKI-002-003 | API automation tempts token storage | Credential leak | Keep API automation out of scope; no token examples |
| R-WIKI-002-004 | Editor-specific formatting pollutes generic wiki | Reduced portability | Keep editor-specific instructions in docs, not core generated pages unless generic |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| WIKI-002-T1 | UX Writer | Add editor workflow docs for Joplin/Obsidian-style usage | README/manual diff reviewed |
| WIKI-002-T2 | Implementer | Improve generated block guidance text without changing source-of-truth semantics | Wiki tests pass |
| WIKI-002-T3 | Test Architect | Add editor folder smoke fixture/validation | Focused wiki tests pass |
| WIKI-002-T4 | QA | Run `mnemosyne wiki rebuild/status/lint` against fixture root | CLI smoke evidence recorded |

## Verification Commands

```bash
python -m pytest tests/test_llm_wiki.py tests/test_cli.py --tb=short -q
ruff check mnemosyne tests
mypy mnemosyne
git diff --check
```

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-WIKI-002-001 | Docs | Joplin/editor workflow documented in README and Korean manual |
| DOD-WIKI-002-002 | Generated guidance | Pages explain generated vs manual edit boundaries |
| DOD-WIKI-002-003 | Smoke fixture | Editor-neutral folder shape verified without live editor dependency |
| DOD-WIKI-002-004 | Quality | Focused tests, ruff, mypy, diff hygiene pass |


## Implementation Result

Completed: 2026-05-02 21:55:38 NZST

| Requirement | Result | Evidence |
|---|---|---|
| REQ-WIKI-002-001 | PASS | README/manual document stable `index.md`, `log.md`, `sources/<domain>/`, and `entities/<type>/` folder contract |
| REQ-WIKI-002-002 | PASS | Generated source/entity/index pages include `## Editing guidance` explaining generated markers and manual note zones |
| REQ-WIKI-002-003 | PASS | README/manual provide token-free Joplin Markdown/folder import guidance and wiki-link caveats |
| REQ-WIKI-002-004 | PASS | `test_editor_neutral_folder_shape_smoke_fixture` validates index/log/source/entity pages, frontmatter, markers, and links without live editor dependency |
| REQ-WIKI-002-005 | PASS | `mnemosyne wiki --help` includes editor-neutral Markdown, explicit `--wiki-root`, and no-token guidance |

Verification evidence:

```text
python -m pytest tests/test_llm_wiki.py tests/test_cli.py --tb=short -q
45 passed in 1.54s

pytest -q
452 passed in 10.38s

ruff check mnemosyne tests
All checks passed!

mypy mnemosyne
Success: no issues found in 37 source files

python -m mnemosyne wiki rebuild/status/lint --format json
CLI smoke passed against temp DB/wiki roots
```
