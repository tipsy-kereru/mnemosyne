# Moon Cell Follow-Up Candidate List

Generated: 2026-05-03 08:35:34 NZST
Updated: 2026-06-20 22:50:19 NZST

## Source Evidence

This list was derived from completed LLM Wiki work, current Moon Cell backlog,
handoff warnings, and the 2026-06-20 OpenKB comparison architecture audit.

## Candidate SPECs

| SPEC ID | Title | Status | Priority | Risk | Source |
|---|---|---|---|---|---|
| SPEC-LONGDOC-001 | PageIndex-style long-doc tree indexing | planned (Laplace ISSUE-0001 draft) | high | high | 2026-06-20 OpenKB gap audit |
| SPEC-NLQUERY-001 | NL query + multi-turn chat layer | planned (Laplace ISSUE-0002 draft) | high | medium | 2026-06-20 OpenKB gap audit |
| SPEC-WIKI-008 | Large Vault Incremental Index Optimization | candidate | low | medium | benchmark-gated; 0 wiki pages currently |

## Recommended Order

| Order | SPEC | Reason |
|---|---|---|
| 1 | SPEC-LONGDOC-001 | NL query depends on long-doc retriever; unblocks SPEC-NLQUERY-001 T4 |
| 2 | SPEC-NLQUERY-001 | Builds on LONGDOC retriever + FTS5; user-facing value |
| 3 | SPEC-WIKI-008 | Re-run when vault size grows; benchmark-gated |

## Current Remaining List

| Item | Status | Candidate SPEC |
|---|---|---|
| Long-document tree indexing + retrieval | Planned (Laplace ISSUE-0001) | SPEC-LONGDOC-001 |
| NL query + chat layer | Planned (Laplace ISSUE-0002) | SPEC-NLQUERY-001 |
| Semantic/LLM contradiction detection | Completed / opt-in local only | SPEC-WIKI-006 |
| Safe stale page/fact pruning with tombstones | Completed | SPEC-WIKI-007 |
| Root bridge and `.moon-cell` tracking policy | Completed 2026-05-04 | SPEC-HARNESS-001 |
| Async I/O design | T1/T2/T3/T4 complete | SPEC-ARCH-ASYNC-001 |
| Large wiki/vault index performance | Open / benchmark first (0 pages) | SPEC-WIKI-008 |
| External Tool Integration API | Completed | SPEC-JOPLIN-001 |

## Laplace Issue Mapping

| Laplace Issue | SPEC | Risk | Phase Route | Approval Gate |
|---|---|---|---|---|
| ISSUE-0001 | SPEC-LONGDOC-001 | high | pm → dev → review → **security** | `/laplace:approve ISSUE-0001` |
| ISSUE-0002 | SPEC-NLQUERY-001 | medium | pm → dev → review | `/laplace:approve ISSUE-0002` |

## Promotion Rule

Move a candidate to `planned` only when the user selects it or a future Moon
Cell planning pass explicitly prioritizes it. Candidate status does not
authorize product implementation. SPEC-LONGDOC-001 and SPEC-NLQUERY-001 are
`planned` (user-approved 2026-06-20) but Laplace drafts remain unapproved —
no implementation until `/laplace:approve` runs.
