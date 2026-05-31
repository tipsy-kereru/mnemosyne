# Moon Cell Follow-Up Candidate List

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-05-04 13:28:55 NZST

## Source Evidence

This list was derived from completed LLM Wiki work, current Moon Cell backlog, and handoff warnings.

## Candidate SPECs

| SPEC ID | Title | Status | Priority | Risk | Source |
|---|---|---|---|---|---|
| SPEC-WIKI-005 | Conflict Resolution Review UX and CLI | completed | high | medium | Completed by `$moon-cell run SPEC-WIKI-005` |
| SPEC-WIKI-006 | Optional Semantic Contradiction Discovery | completed | medium | high | Completed by `$moon-cell run SPEC-WIKI-006` |
| SPEC-WIKI-007 | Wiki Prune, Stale Marker, and Tombstone Reconciliation | completed | medium | high | Completed by `$moon-cell run SPEC-WIKI-007` |
| SPEC-WIKI-008 | Large Vault Incremental Index Optimization | candidate | low | medium | benchmark-gated; 0 wiki pages currently; promote when vault exceeds performance threshold |
| SPEC-ARCH-ASYNC-001 | Async I/O Feasibility and API Boundary Design | planned / T3 deferred | low | medium-high | T1/T2 design complete 2026-05-04; T3 gated on benchmark — 10 URLs: 1.28s < 30s threshold; re-run benchmark when batch ingest load increases |
| SPEC-HARNESS-001 | Root Bridge and Moon Cell Tracking Policy | completed | low | low-medium | Completed 2026-05-04: `!.moon-cell/` gitignore exception + AGENTS.md pointer added |

## Recommended Order

| Order | SPEC | Reason |
|---|---|---|
| 1 | SPEC-WIKI-008 | Re-run when vault size grows; benchmark-gated. |
| 2 | SPEC-ARCH-ASYNC-001 T3 | Re-run benchmark when batch ingest load increases; design already complete. |

## Current Remaining List

| Item | Status | Candidate SPEC |
|---|---|---|
| Conflict resolution UX for `resolution` metadata | Completed | SPEC-WIKI-005 |
| Semantic/LLM contradiction detection | Completed / opt-in local only | SPEC-WIKI-006 |
| Safe stale page/fact pruning with tombstones | Completed | SPEC-WIKI-007 |
| Root bridge and `.moon-cell` tracking policy | **Completed 2026-05-04** | SPEC-HARNESS-001 |
| Async I/O design | **T1/T2 complete; T3 deferred** (1.28s < 30s) | SPEC-ARCH-ASYNC-001 |
| Large wiki/vault index performance | Open / benchmark first (0 pages) | SPEC-WIKI-008 |

## Promotion Rule

Move a candidate to `planned` only when the user selects it or a future Moon Cell planning pass explicitly prioritizes it. Candidate status does not authorize product implementation.
