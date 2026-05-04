# Context Handoff

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-05-04 18:55:27 NZST

## Current Status

Session 2026-05-04: SPEC-BENCH-001 completed. Benchmark harness fully implemented: `scripts/bench/gen_large_vault.py` (500+200 fixture pages), `scripts/bench/gen_llm_batch.sh`, `scripts/bench/clean_fixtures.sh`, extended `benchmark_async.sh` (B1-B6, decision matrix, result recording), and `.moon-cell/docs/BENCHMARK_RESULTS.md`. SPEC-HARNESS-001 completed earlier today. `.moon-cell/` tracking policy: `!.moon-cell/` gitignore exception. AGENTS.md root bridge pointer added. 20 SPECs completed. 465 tests pass.

| Category | Status | Evidence |
|---|---|---|
| Completed SPECs | 20 | SPEC-BENCH-001 completed 2026-05-04 |
| Active planned SPECs | 1 | SPEC-ARCH-ASYNC-001 (T3/T4 benchmark-gated on B1 or B2) |
| Remaining candidate SPECs | 1 | SPEC-WIKI-008 (benchmark-gated; fixtures now available via gen_large_vault.py) |
| Focused tests | PASS | 85 passed |
| Full tests | PASS | 465 passed |
| Static checks | PASS | ruff clean; mypy clean |
| Benchmark harness | READY | Run `bash benchmark_async.sh` after `python3 scripts/bench/gen_large_vault.py` |
| Harness tracking | auto-tracked | `.moon-cell/` tracked via `!.moon-cell/` gitignore exception (SPEC-HARNESS-001) |

## SPEC-WIKI-006 Result

| Requirement | Result |
|---|---|
| Candidate schema | Persists `review/semantic-contradictions.json` with schema `mnemosyne.semantic_contradiction_candidates.v1`, distinct from deterministic `properties["conflicts"]` |
| Opt-in execution | Adds `mnemosyne wiki semantic-contradictions`; payload discloses `processing_mode: local-offline`, `remote_model: false` |
| Evidence-first output | Candidates include source references, bounded redacted excerpts, confidence, uncertainty wording, rationale, generated-at metadata |
| Safety boundaries | Raw source excerpts require explicit `--include-raw-excerpts`; graph facts/pages are not merged, resolved, or deleted |
| Separate status/lint | Persisted semantic candidates appear under `semantic_contradictions` status and `semantic-contradiction-candidate` lint warnings |

## SPEC-ARCH-ASYNC-001 Design Result (T1/T2)

| Item | Decision |
|---|---|
| I/O zones mapped | SQLite (local, fast), Filesystem (local, fast), Network+LLM (slow, N×latency) |
| No existing async | Confirmed: zero `async def`/`await`/`asyncio` in codebase |
| Boundary selected | Option B: targeted async on `URLFetcher` + `LLMBridge` + batch `Ingester` only |
| Pattern | Additive async methods (`fetch_async`, `extract_async`, `add_urls_async`); all sync APIs preserved |
| SQLite/filesystem | Excluded from async — local I/O is fast; `aiosqlite`/`aiofiles` overhead not justified |
| Benchmark gate | T3 shall not start until at least one workload threshold is exceeded (see SPEC) |
| Concurrency limit | LLM calls: semaphore of 5 concurrent requests to avoid rate-limiting |
| HTTP client | httpx preferred for async URL fetch (cleaner API; no sync-layer dependency added) |

## SPEC-HARNESS-001 Result

| Decision | Outcome |
|---|---|
| Tracking policy | Option B: `.gitignore` `!.moon-cell/` exception — no more `git add -f` needed |
| Root bridge | Option Y: `AGENTS.md` now has Moon Cell pointer section (`.moon-cell/MANIFEST.md`, `CONTEXT_HANDOFF.md`, `TASK_ROUTING.md`) |
| Files changed | `.gitignore`, `AGENTS.md` |
| Not changed | `CLAUDE.md` (user did not select) |

## Remaining Candidate List

| Remaining Item | Candidate SPEC | Priority | Risk | Notes |
|---|---|---|---|---|
| Large wiki/vault index performance | SPEC-WIKI-008 | low | medium | Benchmark-gated; 0 wiki pages currently |

## Recommended Order (Next Steps)

| Order | Action | Reason |
|---|---|---|
| 1 | Run SPEC-ARCH-ASYNC-001 benchmarks | Decide whether T3/T4 implementation is justified |
| 2 | SPEC-WIKI-008 | Only after benchmark evidence; overlaps with async work |
| 3 | SPEC-HARNESS-001 | Harness policy cleanup is optional and not product-critical |

## Decisions Made

| ID | Decision | Rationale |
|---|---|---|
| DEC-001 | Preserve `.moon-cell/` as harness source of truth | Existing Moon Cell convention and user asked to expose ignored artifacts |
| DEC-002 | Use `git add -f .moon-cell` instead of editing `.gitignore` | Satisfies tracking request without weakening local-only ignore defaults for future scratch state |
| DEC-003 | `semantic-contradictions` is explicit and local/offline | Avoids accidental semantic review and remote privacy exposure |
| DEC-004 | Semantic candidates are review items only | Prevents false certainty and keeps deterministic conflicts separate |
| DEC-005 | Raw source excerpts require explicit opt-in | Minimizes sensitive raw text exposure while still allowing bounded evidence when requested |
| DEC-006 | Discovery never mutates graph facts or deletes wiki pages | Semantic review cannot become an automatic resolution/prune mechanism |

## Files Changed In SPEC-WIKI-006

| Path | Change |
|---|---|
| `mnemosyne/wiki/llm_wiki.py` | Added semantic candidate schema, local heuristic detector, persistence, review page, status stats, and lint warnings |
| `mnemosyne/wiki/cli.py` | Added `semantic-contradictions` subcommand with `--write` and `--include-raw-excerpts` |
| `mnemosyne/cli.py` | Added top-level parser/delegation and examples for semantic discovery |
| `tests/test_llm_wiki.py` | Added opt-in/local/separate semantic review tests and CLI write coverage |
| `tests/test_cli.py` | Added top-level wiki help assertion for `semantic-contradictions` |
| `README.md` | Documented semantic discovery safety boundary and usage |
| `매뉴얼.md` | Added Korean semantic discovery docs |
| `CHANGELOG.md` | Added product changelog entry for SPEC-WIKI-006 |
| `.moon-cell/specs/SPEC-WIKI-006.md` | Promoted to completed with implementation evidence |
| `.moon-cell/MANIFEST.md` | Refreshed SPEC inventory and evidence |
| `.moon-cell/docs/harness/TASK_ROUTING.md` | Moved SPEC-WIKI-006 to completed and reprioritized candidates |
| `.moon-cell/docs/harness/CHANGELOG.md` | Added 0.2.2 completion entry |
| `.moon-cell/docs/harness/QUALITY_GATES.md` | Added 465-test and semantic CLI smoke evidence |
| `.moon-cell/docs/harness/CONTEXT_HANDOFF.md` | Refreshed handoff with SPEC-WIKI-006 result |
| `.moon-cell/VERSION` | Updated harness timestamp |

## Files Intentionally Not Changed

| Path | Reason |
|---|---|
| `.gitignore` | User allowed force-add fallback; tracking policy remains candidate SPEC-HARNESS-001 |
| `AGENTS.md` | Root bridge changes require explicit G-BRIDGE confirmation |
| `CLAUDE.md` | Root bridge changes require explicit G-BRIDGE confirmation |

## Commands Run

```bash
python -m pytest tests/test_llm_wiki.py tests/test_cli.py --tb=short -q
python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q
python -m pytest -q
ruff check mnemosyne tests
mypy mnemosyne
python -m mnemosyne wiki semantic-contradictions --wiki-root "$tmp/wiki" --db-path "$tmp/kg.db" --format json --write
python -m mnemosyne wiki status --wiki-root "$tmp/wiki" --db-path "$tmp/kg.db" --format json
python -m mnemosyne wiki lint --wiki-root "$tmp/wiki" --db-path "$tmp/kg.db" --format json
git diff --check
git add -f .moon-cell
git diff --cached --check
```

## Checks Run

| Check | Result |
|---|---|
| SPEC-WIKI-006 inspected | PASS |
| Opt-in local semantic discovery | PASS |
| Distinct semantic schema persistence | PASS |
| Evidence redaction and uncertainty wording | PASS |
| False-positive fixture | PASS |
| Status/lint semantic separation | PASS |
| Focused wiki/ingest/CLI tests | PASS: 85 passed |
| Full tests | PASS: 465 passed |
| Static checks | PASS: ruff clean; mypy clean |
| CLI smoke | PASS |
| Forced staging | PASS: `.moon-cell` staged with `git add -f` |

## Next Recommended Action

1. Run `$moon-cell run SPEC-ARCH-ASYNC-001` if you want the async I/O architecture decision next.
2. Run `$moon-cell run SPEC-WIKI-008` only if large-vault performance evidence is now a priority.
