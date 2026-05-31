---
id: SPEC-WIKI-003
version: "0.1.0"
status: completed
created: "2026-05-02 13:19:03 NZST"
updated: "2026-05-03 08:26:40 NZST"
author: Moon Cell Harness
priority: medium
risk: medium-high
owner_role: Spec Architect / Solution Architect
reviewer_role: Security Reviewer / Test Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-WIKI-003.md
related_backlog: "FUTURE-005"
---

# SPEC-WIKI-003: Conflict-Metadata-Based Contradiction Summaries

Generated: 2026-05-02 13:19:03 NZST
Updated: 2026-05-03 08:26:40 NZST

Canonical location: `.moon-cell/specs/SPEC-WIKI-003.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Parent work | SPEC-WIKI-001 added conflict metadata during entity merge |
| Target gate | QG-006 plus contradiction-summary regression tests |
| Implementation started | 2026-05-03 08:26:40 NZST |
| Implementation completed | 2026-05-03 08:26:40 NZST |

## Implementation Summary

SPEC-WIKI-003 is implemented as a deterministic, metadata-only contradiction
review layer.

| Area | Result |
|---|---|
| Conflict adapter | Legacy `seen_at` records, current `detected_at` records, missing sources, and resolved statuses normalize into `WikiContradiction` records |
| Entity pages | Unresolved conflicts render as cautious `## Potential contradictions` / `Needs review` sections |
| Safety | Conflict values use the same redaction policy as wiki source excerpts; raw `conflicts` dictionaries are not dumped in properties |
| Status/lint | `wiki status --db-path --format json` includes contradiction totals; `wiki lint --db-path` warns on unresolved contradictions; `--strict` fails on warnings |
| Ingest metadata | New conflict records include `source_id`, `detected_at`, legacy `seen_at`, and `resolution: unresolved` |

## Verification Evidence

| Check | Result |
|---|---|
| Focused wiki/ingest/CLI tests | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 79 passed |
| Full pytest | `pytest -q` → 459 passed |
| Static checks | `ruff check mnemosyne tests` clean; `mypy mnemosyne` success across 37 source files |
| CLI smoke | `mnemosyne wiki rebuild/status/lint --format json` passed against temp DB/wiki roots, including strict unresolved-contradiction failure |

## Problem Statement

SPEC-WIKI-001 preserves conflicting entity property values under conflict metadata instead of silently overwriting facts. That prevents data loss, but the conflict is not yet promoted into a human/LLM-readable contradiction summary. Agents and users can still miss that two sources disagree unless they inspect raw properties.

The project needs a deterministic, safe contradiction layer that surfaces conflicts as evidence-backed review items without claiming more certainty than the graph supports.

## Goals

| ID | Goal |
|---|---|
| G-WIKI-003-001 | Convert existing conflict metadata into readable contradiction sections in entity pages and status/lint outputs. |
| G-WIKI-003-002 | Preserve source attribution for each conflicting value. |
| G-WIKI-003-003 | Distinguish deterministic property conflicts from LLM-inferred semantic contradictions. |
| G-WIKI-003-004 | Keep the first implementation offline and dependency-free. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-WIKI-003-001 | Do not add remote LLM calls as a required contradiction detector. |
| NG-WIKI-003-002 | Do not auto-resolve contradictions or delete conflicting facts. |
| NG-WIKI-003-003 | Do not present conflicts as verified falsehoods; they are review candidates. |
| NG-WIKI-003-004 | Do not redesign the full extraction schema in this SPEC. |

## Current Evidence

| Evidence | Result | Source |
|---|---|---|
| Entity merge preserves conflicts | Conflicting properties are stored under `properties["conflicts"]` | `mnemosyne/ingest/ingester.py` |
| Entity history records updates | Existing entities get update history rows | `mnemosyne/graph/knowledge_graph.py` |
| Wiki pages can show properties | Entity pages render graph-backed property sections | `mnemosyne/wiki/llm_wiki.py` |
| Lint/status exist | Wiki commands can expose consistency signals | `mnemosyne/wiki/cli.py` |

## Data Contract

Conflict metadata should remain machine-readable and source-attributed.

Recommended shape:

```json
{
  "conflicts": {
    "property_name": [
      {
        "existing": "old value",
        "incoming": "new value",
        "source_file": "raw/source/path.md",
        "source_id": "optional-source-id",
        "detected_at": "ISO timestamp",
        "resolution": "unresolved"
      }
    ]
  }
}
```

If current storage differs, implementation should add a compatibility adapter rather than breaking existing conflict records.

## Requirements

### REQ-WIKI-003-001: Conflict Metadata Normalization

**EARS:** When entity conflicts are read, the system shall normalize legacy and new conflict metadata into one internal shape.

Acceptance criteria:
- Existing SPEC-WIKI-001 conflict records continue to work.
- Normalized conflicts include property name, old value, new value, source reference when available, and unresolved status.
- Missing source attribution is represented as `unknown`, not guessed.

### REQ-WIKI-003-002: Entity Page Contradiction Section

**EARS:** When an entity has unresolved conflicts, its wiki page shall include a generated contradiction/review section.

Acceptance criteria:
- Section is generated from graph properties and preserved during rebuild.
- Each conflict lists property, competing values, and source references when available.
- Language uses cautious labels such as "Potential contradiction" or "Needs review".

### REQ-WIKI-003-003: Wiki Status and Lint Signals

**EARS:** When users run wiki status or lint, unresolved contradictions shall be visible as review signals.

Acceptance criteria:
- `mnemosyne wiki status --format json` includes contradiction counts when DB is available.
- `mnemosyne wiki lint` emits warnings for unresolved contradictions, not blocking errors by default.
- `--strict` can fail on unresolved contradiction warnings.

### REQ-WIKI-003-004: Resolution Metadata

**EARS:** When a contradiction is reviewed, the system shall support recording resolution metadata without deleting source evidence.

Acceptance criteria:
- Data model supports at least `unresolved`, `accepted_existing`, `accepted_incoming`, `superseded`, and `ambiguous` statuses.
- Resolved conflicts remain auditable in entity history or properties.
- No CLI mutation command is required in the first implementation unless explicitly added.

### REQ-WIKI-003-005: Deterministic First Pass

**EARS:** When contradiction summaries are generated, the first pass shall rely on deterministic conflict metadata only.

Acceptance criteria:
- No remote LLM dependency.
- No semantic contradiction claims beyond stored conflicts.
- Optional future semantic/LLM contradiction detection is documented as a later SPEC.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-WIKI-003-001 | False certainty | Users may treat conflicts as truth judgments | Use cautious wording and source evidence |
| R-WIKI-003-002 | Metadata schema drift | Existing conflict records may not match new shape | Add normalization adapter and tests |
| R-WIKI-003-003 | Sensitive values in conflicts | Secrets could be surfaced in wiki summaries | Reuse redaction policy before rendering values |
| R-WIKI-003-004 | Resolution UX is underspecified | Conflicts remain noisy | Start read-only; add mutation UX in later SPEC if needed |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| WIKI-003-T1 | Solution Architect | Finalize conflict metadata compatibility adapter | Unit tests for legacy/new shapes |
| WIKI-003-T2 | Security Reviewer | Define redaction behavior for conflict values | Secret-pattern tests pass |
| WIKI-003-T3 | Implementer | Render contradiction section in entity pages | Wiki rebuild tests pass |
| WIKI-003-T4 | Implementer | Add status/lint contradiction counts and warnings | CLI JSON tests pass |
| WIKI-003-T5 | Test Architect | Add regression tests for unresolved/resolved conflicts | Focused and full tests pass |

## Verification Commands

```bash
python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q
ruff check mnemosyne tests
mypy mnemosyne
git diff --check
```

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-WIKI-003-001 | Conflict adapter | Legacy/current conflict records normalize correctly |
| DOD-WIKI-003-002 | Entity page | Unresolved conflicts render as cautious review summaries |
| DOD-WIKI-003-003 | CLI | Status/lint expose contradiction counts and warnings |
| DOD-WIKI-003-004 | Safety | Conflict values are redacted consistently with wiki excerpt policy |
| DOD-WIKI-003-005 | Quality | Focused tests, full tests, ruff, mypy, diff hygiene pass |
