# Moon Cell Harness Changelog

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-05-04 18:55:27 NZST

## [0.2.6] - 2026-05-04

### Completed
- SPEC-BENCH-001: Benchmark Harness and Fixture Setup — fully implemented.
- Fixture generators: `scripts/bench/gen_large_vault.py` (500+200 pages), `scripts/bench/gen_llm_batch.sh` (5 files), `scripts/bench/clean_fixtures.sh` (cleanup).
- Extended `benchmark_async.sh` with B1 (PDF URLs), B2 (LLM batch, API-key gated), B4 (wiki status), B5 (wiki lint), B6 (wiki rebuild dry-run), threshold env vars, decision matrix, and result recording.
- Created `.moon-cell/docs/BENCHMARK_RESULTS.md` with initial baseline entry.
- Updated `BENCHMARK_GUIDE.md` with Quick Start section referencing fixture scripts.

### Evidence
- Fixture generation: 500 entity + 200 source pages created and cleaned (0 residue verified).
- `python3 -m pytest -q` → 465 passed.
- `python3 -m ruff check scripts/bench/` → All checks passed.
- `git diff mnemosyne/` → empty (DOD-007: harness-only).

### Preserved
- No product code changed (`mnemosyne/` untouched).
- Root `AGENTS.md`, `CLAUDE.md` not modified.

## [0.2.5] - 2026-05-04

### Planned
- SPEC-BENCH-001: Benchmark Harness and Fixture Setup — new SPEC written.
- Unblocks SPEC-ARCH-ASYNC-001 T3 (async I/O) and SPEC-WIKI-008 T1 (large vault optimization).
- Covers: fixture generation (500 entity + 200 source pages), extended benchmark_async.sh
  (B2 LLM batch, B4–B6 vault ops), result recording to BENCHMARK_RESULTS.md,
  and harness verification.

### Added
- `.moon-cell/docs/BENCHMARK_GUIDE.md` — benchmark preparation reference document.
- `.moon-cell/specs/SPEC-BENCH-001.md` — 17 EARS requirements, 4 tasks, 7 DOD checks.

## [0.2.4] - 2026-05-04

### Completed
- SPEC-HARNESS-001: Root Bridge and Moon Cell Tracking Policy.
- `.gitignore` updated: `.moon-cell/` exception (`!.moon-cell/`) — no more `git add -f` required.
- `AGENTS.md` updated: Moon Cell pointer section added (source of truth, MANIFEST, CONTEXT_HANDOFF, TASK_ROUTING paths).

### Preserved
- `CLAUDE.md` not modified (not selected by user).
- No product code changed.
- All 465 tests continue to pass unchanged.

## [0.2.3] - 2026-05-04

### Planned
- SPEC-ARCH-ASYNC-001: Async I/O Feasibility and API Boundary Design promoted from candidate to planned.
- T1 (I/O hotspot map) and T2 (API review + benchmark criteria) completed — design-only, no product code changed.

### Design Decisions (T1/T2)
- I/O zones mapped: SQLite (local, fast), Filesystem (local, fast), Network+LLM (primary bottleneck).
- Zero async code confirmed in codebase at time of analysis.
- Boundary: additive async methods on `URLFetcher`, `LLMBridge`, and batch `Ingester` only.
- SQLite and filesystem excluded from async — local I/O overhead not justified.
- T3/T4 (implementation) gated on benchmark evidence (workload thresholds defined in SPEC).

### Preserved
- No product code changed during T1/T2 planning pass.
- All 465 tests continue to pass unchanged.
- Root `AGENTS.md`, `CLAUDE.md`, `.gitignore` not modified.

## [0.2.2] - 2026-05-03

### Completed
- SPEC-WIKI-006: Optional Semantic Contradiction Discovery.
- Added explicit `mnemosyne wiki semantic-contradictions` local/offline review workflow.
- Added distinct semantic review schema under `review/semantic-contradictions.*`.
- Added separate status/lint reporting for persisted semantic candidates.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 85 passed.
- `pytest -q` → 465 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke: `mnemosyne wiki semantic-contradictions --write --format json` persisted review candidates with `processing_mode: local-offline`.

### Preserved
- No remote model calls are enabled.
- Semantic candidates are not deterministic conflicts, truth judgments, graph merges, or deletes.
- Root `AGENTS.md`, `CLAUDE.md`, and `.gitignore` not modified.

## [0.2.1] - 2026-05-03

### Completed
- SPEC-WIKI-007: Wiki Prune, Stale Marker, and Tombstone Reconciliation.
- Added non-destructive stale candidate planning through `mnemosyne wiki prune`.
- Added tombstone Markdown records with manual-note recovery previews and zero-delete guarantees.
- Updated status/lint stale signals and documentation.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 83 passed.
- `pytest -q` → 463 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|prune --format json` succeeded, including tombstone writes.

### Preserved
- No wiki pages or graph facts are deleted by prune/tombstone flow.
- Manual notes outside generated markers are preserved in original pages and tombstone previews.
- Root `AGENTS.md`, `CLAUDE.md`, and `.gitignore` not modified.

## [0.2.0] - 2026-05-03

### Completed
- SPEC-WIKI-005: Conflict Resolution Review UX and CLI.
- Added `mnemosyne wiki contradictions` for stable conflict IDs and graph-backed review item listing.
- Added `mnemosyne wiki resolve` for metadata-only resolution updates with optional note/reviewer and dry-run support.
- Updated docs and harness routing after promoting SPEC-WIKI-005 from candidate to completed.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 81 passed.
- `pytest -q` → 461 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|contradictions|resolve --format json` succeeded, including dry-run and persisted resolution behavior.

### Preserved
- No conflict evidence values are deleted or overwritten by resolve.
- Reviewer identity remains optional; no OS identity is collected by default.
- Root `AGENTS.md`, `CLAUDE.md`, and `.gitignore` not modified.

## [0.1.9] - 2026-05-03

### Planned
- Added follow-up candidate list for remaining Moon Cell work.
- Drafted candidate SPECs for conflict resolution UX, semantic contradiction discovery, stale/tombstone reconciliation, large-vault indexing, async I/O boundary design, and root bridge/tracking policy.
- Updated task routing with candidate-only promotion rules and recommended order.

### Evidence
- Inspected `.moon-cell/MANIFEST.md`, `TASK_ROUTING.md`, `CONTEXT_HANDOFF.md`, SPEC-WIKI deferred follow-ups, and current backlog entries.
- No product implementation started; all new SPECs are `status: candidate`.
- QG-004 docs refresh checks: `git diff --check` and `git diff --cached --check`.

### Preserved
- No root `AGENTS.md`, `CLAUDE.md`, or `.gitignore` changes.
- Candidate SPECs do not authorize implementation until promoted to planned.

## [0.1.8] - 2026-05-03

### Completed
- SPEC-WIKI-003: Conflict-Metadata-Based Contradiction Summaries.
- Added deterministic contradiction/review sections from graph conflict metadata.
- Added status and lint review signals for unresolved contradictions.
- Added conflict metadata normalization and redaction coverage for legacy/current records.
- Marked all planned LLM Wiki follow-up specs complete.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` → 79 passed.
- `pytest -q` → 459 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|status|lint --format json` succeeded, including unresolved contradiction warning and strict-lint failure behavior.

### Preserved
- No remote LLM dependency added.
- No automatic contradiction resolution or source evidence deletion added.
- Root `AGENTS.md` and `CLAUDE.md` not modified.

## [0.1.7] - 2026-05-03

### Completed
- SPEC-WIKI-004: Multi-Process Concurrent Wiki Writer Locking.
- Added stdlib atomic lock-file acquisition for wiki write paths with owner-token-safe release.
- Added lock timeout errors with stable JSON code `wiki-lock-timeout` and stale-lock diagnostic metadata.
- Updated docs with timeout, read-only command behavior, local-filesystem scope, and stale-lock recovery guidance.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q` → 39 passed.
- `pytest -q` → 456 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|status|lint --format json --lock-timeout 1` succeeded.

### Preserved
- No new third-party dependency added.
- Read-only `wiki status` and `wiki lint` remain unlocked by default.
- Root `AGENTS.md` and `CLAUDE.md` not modified.

## [0.1.6] - 2026-05-02

### Completed
- SPEC-WIKI-002: Joplin / Editor UX Polish for LLM Wiki.
- Added generated-page editing guidance for rebuildable sections and manual note safe zones.
- Added editor-neutral folder shape smoke coverage without requiring a live Joplin/Obsidian dependency.
- Updated CLI help, README, and Korean manual with explicit `--wiki-root`, token-free Joplin import guidance, and wiki-link caveats.

### Evidence
- `python -m pytest tests/test_llm_wiki.py tests/test_cli.py --tb=short -q` → 45 passed.
- `pytest -q` → 452 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|status|lint --format json` succeeded.

### Preserved
- No Joplin API token or live editor dependency introduced.
- Root `AGENTS.md` and `CLAUDE.md` not modified.

## [0.1.5] - 2026-05-02

### Added
- Added `.moon-cell/specs/SPEC-WIKI-002.md` for Joplin/editor UX polish of the generated LLM Wiki.
- Added `.moon-cell/specs/SPEC-WIKI-003.md` for deterministic contradiction summaries based on existing conflict metadata.
- Added `.moon-cell/specs/SPEC-WIKI-004.md` for stdlib multi-process wiki writer locking.
- Updated task routing with planned follow-up SPEC ownership, reviewers, and recommended execution order.

### Evidence
- Planning inputs inspected: SPEC-WIKI-001 implementation state, current wiki/ingest CLI surfaces, `.gitignore`, manifest, task routing, and handoff docs.
- No product implementation started for SPEC-WIKI-002/003/004.
- `.moon-cell` artifacts staged with `git add -f` because `.gitignore` marks `.moon-cell/` local-only.

### Preserved
- Root `AGENTS.md` and `CLAUDE.md` not modified.
- `.gitignore` not changed; forced staging was used instead of weakening local-only ignore defaults.

## [0.1.4] - 2026-05-02

### Completed
- SPEC-WIKI-001: LLM Wiki Hardening and Knowledge Graph Synchronization.
- Added rebuildable/lintable/status-checkable LLM Wiki maintenance workflow through `mnemosyne wiki status|lint|rebuild|doctor`.
- Added compact frontmatter metadata for generated wiki pages, safe excerpt defaults, redacted opt-in excerpts, stable slug collision disambiguation, and atomic generated writes.
- Added graph merge semantics for existing entities/relations, including conflict preservation and entity history update events.
- Added wiki rebuild from graph rows while preserving manual notes outside generated markers.
- Updated README and Korean manual to describe the graph + LLM Wiki workflow and safe excerpt policy.

### Evidence
- `pytest -q` → 450 passed.
- `ruff check mnemosyne tests` → All checks passed.
- `mypy mnemosyne` → Success: no issues found in 37 source files.
- `git diff --check` → no whitespace errors.
- CLI smoke against temp DB/wiki roots: `python -m mnemosyne wiki rebuild|status|lint --format json` succeeded.

### Preserved
- Root `AGENTS.md` and `CLAUDE.md` not modified.
- `.moon-cell/` remains the harness source of truth and is ignored by git.
- Editor-specific Joplin/Obsidian polish remains deferred rather than coupled to core graph/wiki correctness.

## [0.1.3] - 2026-04-30

### Completed
- SPEC-INGEST-001: Knowledge Graph Ingestion Pipeline — `mnemosyne add` / `mnemosyne update` CLI commands, vendor-neutral LLM bridge (Claude/OpenAI/Gemini/CLI fallback), URL fetcher (arXiv, PDF, webpage), incremental SHA-256 hash-based update, skill interface. 25 new tests added.
- SPEC-WARN-001: Systematic Pytest Warning Remediation — replaced all 10 `datetime.utcnow()` call sites across 5 files with `datetime.now(timezone.utc)`. Zero DeprecationWarning under `-W error::DeprecationWarning`.

### Fixed
- `pyproject.toml` `requires-python` restored to `>=3.11` (corrects unintentional downgrade to `>=3.10` in prior session).
- `test_pyproject_requires_python` passes again.

### Evidence
- `python3 -m pytest -W error::DeprecationWarning -q` → 440 passed, 0 warnings.
- All 10 completed SPECs reflected in MANIFEST.md and TASK_ROUTING.md.

### Preserved
- Root `AGENTS.md` and `CLAUDE.md` not modified.

## [0.1.2] - 2026-04-29

### Added
- Added `.moon-cell/specs/SPEC-WARN-001.md` as the Moon Cell controlled SPEC for systematic pytest warning remediation.
- Added QG-005 warning-cleanliness gate to `.moon-cell/docs/harness/QUALITY_GATES.md`.
- Added SPEC-WARN-001 to task routing as the active/planned warning remediation work.

### Evidence
- Baseline command: `python3 -m pytest --tb=short -q`.
- Baseline result: 413 passed, 2 skipped, 417 warnings.
- Static sources: seven project-owned `datetime.utcnow()` call sites under `mnemosyne/`.

### Preserved
- No product source code changed in this planning step.
- Root `AGENTS.md` and `CLAUDE.md` remained untouched.

## [0.1.1] - 2026-04-29

### Changed
- Refreshed `.moon-cell/` harness metadata to match current repository evidence.
- Updated quality evidence from older 295/323-test references to current 413 passed / 2 skipped test result.
- Updated SPEC inventory to include completed SPEC-PROD-001, SPEC-PROD-002, and SPEC-RENAME-001.
- Added QG-004 for harness-only changes and root bridge confirmation.
- Updated agent team and task routing for Codex App compatibility while retaining Claude Code bridge state.
- Refreshed context handoff with current safe-update decision and verification evidence.

### Added
- Added `.moon-cell/bridges/codex/MODEL_MAP.md` for Codex App / Codex CLI model-class mapping based on current session metadata.
- Added deferred backlog entries for timezone-aware datetime migration and optional root AGENTS.md Moon Cell bridge.

### Preserved
- Root `AGENTS.md` was not modified.
- Root `CLAUDE.md` was not modified.
- Existing `.moon-cell/bridges/claude-code/MODEL_MAP.md` was retained.

### Verification
- `python3 -m pytest --tb=short -q` -> 413 passed, 2 skipped, 417 warnings.

## [0.1.0] - 2026-04-28

### Added
- Initial Moon Cell harness workspace created.
- Harness style: Hybrid (Audit-first + SPEC-first lite + Karpathy guardrails).
- VERSION, MANIFEST.md, DOC_STYLE.md created.
- HARNESS.md with workflow, confirmation gates, guardrails.
- QUALITY_GATES.md with QG-001 (pre-commit), QG-002 (pre-release), QG-003 (architecture).
- MODEL_ROUTING.md with vendor-neutral model classes.
- bridges/claude-code/MODEL_MAP.md with Claude Code model mapping.
- SKILL_INVENTORY.md with project tools, MoAI skills, and production gaps.
- AGENT_TEAM.md with initial role blueprint.
- CONTEXT_HANDOFF.md initialized.

### Baseline
- Initial baseline recorded 6/6 SPECs completed.
- Initial baseline recorded 295 tests passing, mypy 0 errors, ruff 0 violations.
- Package: mnemosyne-kg v0.1.0, Python 3.11+.
