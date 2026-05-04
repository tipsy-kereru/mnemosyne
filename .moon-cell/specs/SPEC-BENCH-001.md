---
id: SPEC-BENCH-001
version: "1.0.0"
status: completed
created: "2026-05-04 13:28:55 NZST"
updated: "2026-05-04 19:47:27 NZST"
author: Moon Cell Harness
priority: medium
risk: low
owner_role: Test Architect
reviewer_role: Performance Architect
implementation_role: Implementer
source_of_truth: .moon-cell/specs/SPEC-BENCH-001.md
related_backlog: "SPEC-ARCH-ASYNC-001 T3 (gated on B1/B2); SPEC-WIKI-008 T1+ (gated on B4-B6)"
---

# SPEC-BENCH-001: Benchmark Harness and Fixture Setup

Generated: 2026-05-04 13:28:55 NZST
Updated: 2026-05-04 19:47:27 NZST

Canonical location: `.moon-cell/specs/SPEC-BENCH-001.md`.

## Status

| Field | Value |
|---|---|
| Stage | Completed |
| Implementation started | 2026-05-04 |
| Completed | 2026-05-04 19:47:27 NZST |
| Promotion reason | User explicitly requested SPEC be created and implemented to unblock SPEC-ARCH-ASYNC-001 T3 and SPEC-WIKI-008 T1 |

## Implementation Evidence

| Check | Result |
|---|---|
| `scripts/bench/gen_large_vault.py` | Generates 500 entity + 200 source pages; verified counts in /tmp/bench_wiki_test |
| `scripts/bench/gen_llm_batch.sh` | Generates 5 × ~300-word synthetic files at /tmp/bench_llm_*.txt |
| `scripts/bench/clean_fixtures.sh` | Removed 500 entity + 200 source fixture pages; zero residue verified |
| `benchmark_async.sh` B1 | PDF URL fetch × 10; threshold env var support; result recorded |
| `benchmark_async.sh` B2 | LLM batch × 5; API key gated; SKIP message on missing key |
| `benchmark_async.sh` B4/B5/B6 | wiki status/lint/rebuild; 500-page gate; SKIP message below threshold |
| Decision matrix | Printed at end of each run; SPEC-ARCH-ASYNC-001 / SPEC-WIKI-008 verdict |
| Result recording | Appended to `.moon-cell/docs/BENCHMARK_RESULTS.md` per run |
| `git diff mnemosyne/` | Empty — harness-only, no product code changed (DOD-007) |
| `python3 -m pytest -q` | 465 passed |
| `python3 -m ruff check scripts/bench/` | All checks passed |
| Fixture isolation | Cleanup removes only `entity_NNNN.md` / `source_NNNN.md`; real pages untouched |
| Source evidence | BENCHMARK_GUIDE.md; SPEC-ARCH-ASYNC-001 Benchmark Criteria (DOD-002 not met); SPEC-WIKI-008 (0 pages, not measurable) |

## Problem Statement

Two SPECs in this project are currently gated on benchmark evidence before implementation may proceed:

1. **SPEC-ARCH-ASYNC-001 T3** (async I/O for URL fetch and LLM batch ingest) requires
   either a 10-URL serial fetch above 30s or a 5-file LLM batch ingest above 60s. The
   only existing measurement is 1.28s for 10 arXiv abstract URLs (CDN-cached HTML),
   which is unrepresentative of real ingest workloads. PDF URLs and LLM ingest were
   never measured.
2. **SPEC-WIKI-008 T1** (large vault incremental index optimization) requires wiki
   status, lint, and rebuild measurements on a vault of 500+ pages. The current vault
   contains 0 pages, so no measurement is possible.

The existing `benchmark_async.sh` script covers only B1 (URL fetch on abstract pages)
and B3 (wiki lint, currently skipped at <100 pages). Without reproducible fixtures,
extended benchmark sections, and recorded results, neither gate can be cleared and
both downstream SPECs remain blocked indefinitely.

This SPEC defines the **benchmark harness itself** — the fixture generators, the
extended benchmark script, the result-recording protocol, and the verification
procedure — so that future runs are reproducible, isolated from real user data,
and produce evidence that maps directly to gate decisions.

## Goals

| ID | Goal |
|---|---|
| G-BENCH-001-001 | Provide reproducible fixture generation for large wiki vaults (500+ pages) and synthetic LLM batch input (5 files). |
| G-BENCH-001-002 | Extend `benchmark_async.sh` to cover B2 (LLM batch), B4 (wiki status), B5 (wiki lint at scale), and B6 (wiki rebuild dry-run). |
| G-BENCH-001-003 | Record every benchmark run to `.moon-cell/docs/BENCHMARK_RESULTS.md` with timestamp, measured values, and pass/fail per threshold. |
| G-BENCH-001-004 | Make thresholds configurable via environment variables without editing the script. |
| G-BENCH-001-005 | Output a decision matrix at the end of each run identifying which downstream SPECs are unblocked. |
| G-BENCH-001-006 | Isolate fixtures from real user data so benchmarks cannot corrupt `~/mnemosyne/` content. |

## Non-Goals

| ID | Non-Goal |
|---|---|
| NG-BENCH-001-001 | Do not implement the async work itself — that remains SPEC-ARCH-ASYNC-001 T3. |
| NG-BENCH-001-002 | Do not implement incremental index optimization — that remains SPEC-WIKI-008 T3. |
| NG-BENCH-001-003 | Do not introduce a continuous-integration benchmark harness or performance regression dashboard. |
| NG-BENCH-001-004 | Do not benchmark SQLite, raw filesystem, or extraction pipeline zones — out of scope per SPEC-ARCH-ASYNC-001 boundary decision. |
| NG-BENCH-001-005 | Do not require an LLM API key for the harness to be usable — B2 must skip cleanly when no key is set. |
| NG-BENCH-001-006 | Do not modify `mnemosyne/` product code; this SPEC is harness-only. |

## Exclusions (What NOT to Build)

| ID | Exclusion | Rationale |
|---|---|---|
| EX-BENCH-001-001 | No async client implementation | Implementation is downstream (SPEC-ARCH-ASYNC-001 T3); this SPEC only produces evidence to unblock it. |
| EX-BENCH-001-002 | No modification of `URLFetcher`, `LLMBridge`, or `LLMWikiMaintainer` | The harness consumes the existing public sync API and must not change product behavior. |
| EX-BENCH-001-003 | No fixture generation against the real `~/mnemosyne/wiki/` without a distinguishable naming convention | Mixing fixture pages with real pages risks corrupting the user vault. |
| EX-BENCH-001-004 | No persistent cache of benchmark URLs | Each run must measure cold-path behavior; caching defeats the gate. |
| EX-BENCH-001-005 | No alternative benchmark runners (pytest-benchmark, asv, hyperfine) | `benchmark_async.sh` is the canonical runner per BENCHMARK_GUIDE.md; adding alternatives fragments the protocol. |

## Requirements

### REQ-BENCH-001-001: Fixture generation script — large vault

**EARS:** When the operator invokes the large-vault fixture script, the system shall create 500 entity pages and 200 source pages under `${MNEMOSYNE_WIKI_ROOT:-~/mnemosyne/wiki}/` using the naming convention `entity_NNNN.md` and `source_NNNN.md` so fixture pages are distinguishable from real pages.

### REQ-BENCH-001-002: Fixture generation script — LLM batch input

**EARS:** When the operator invokes the LLM batch fixture script, the system shall generate exactly 5 synthetic text files of approximately 300 words each under `/tmp/bench_llm_*.txt`.

### REQ-BENCH-001-003: Fixture cleanup — single command

**EARS:** When the operator invokes the cleanup command, the system shall remove only fixture pages matching `entity_[0-9]*.md` or `source_[0-9]*.md` and remove the LLM batch files, while preserving any non-matching pages in the wiki root.

### REQ-BENCH-001-004: B1 — URL serial fetch (PDFs)

**EARS:** When `benchmark_async.sh` runs benchmark B1, the system shall fetch 10 PDF URLs serially through `URLFetcher.fetch()` using `tempfile.TemporaryDirectory()` as the raw directory and report total elapsed seconds.

### REQ-BENCH-001-005: B2 — LLM batch ingest

**EARS:** When `benchmark_async.sh` runs benchmark B2 and either `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set, the system shall invoke `mnemosyne add` on the 5 LLM fixture files and report total elapsed seconds.

### REQ-BENCH-001-006: B2 — graceful skip on missing API key

**EARS:** While neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` is set, the system shall skip benchmark B2 with a clear `SKIP` message and shall not fail the overall run.

### REQ-BENCH-001-007: B4 — wiki status at scale

**EARS:** When `benchmark_async.sh` runs benchmark B4 and the page count is 500 or more, the system shall measure `mnemosyne wiki status` against the wiki root and report total elapsed seconds.

### REQ-BENCH-001-008: B5 — wiki lint at scale

**EARS:** When `benchmark_async.sh` runs benchmark B5 and the page count is 500 or more, the system shall measure `mnemosyne wiki lint` against the wiki root and report total elapsed seconds.

### REQ-BENCH-001-009: B6 — wiki rebuild dry-run at scale

**EARS:** When `benchmark_async.sh` runs benchmark B6 and the page count is 500 or more, the system shall measure `mnemosyne wiki rebuild --dry-run` against the wiki root and report total elapsed seconds.

### REQ-BENCH-001-010: Threshold check — pass/fail classification

**EARS:** When each benchmark completes, the system shall compare the measured elapsed seconds against the configured threshold and classify the result as PASS (elapsed > threshold, indicating downstream work is justified) or MISS (elapsed ≤ threshold).

### REQ-BENCH-001-011: Threshold configurability

**EARS:** While environment variables `THRESHOLD_URL`, `THRESHOLD_LLM`, `THRESHOLD_WIKI_STATUS`, `THRESHOLD_WIKI_LINT`, and `THRESHOLD_WIKI_REBUILD` are set, the system shall use those values as thresholds for B1, B2, B4, B5, and B6 respectively; otherwise the system shall use defaults of 30, 60, 1, 2, and 5 seconds.

### REQ-BENCH-001-012: Result recording

**EARS:** When `benchmark_async.sh` completes a run, the system shall append a timestamped record to `.moon-cell/docs/BENCHMARK_RESULTS.md` listing each benchmark's measured value, threshold, and pass/fail status.

### REQ-BENCH-001-013: Decision matrix output

**EARS:** When `benchmark_async.sh` completes a run, the system shall print a decision matrix indicating whether SPEC-ARCH-ASYNC-001 T3 is unblocked (B1 OR B2 PASS), whether SPEC-WIKI-008 T1 is unblocked (any of B4/B5/B6 PASS), or whether both remain deferred.

### REQ-BENCH-001-014: Fixture isolation from real data

**EARS:** While benchmarks run against `~/mnemosyne/wiki/`, the system shall not write to, modify, or delete any pages whose filename does not match the fixture naming convention defined in REQ-BENCH-001-001.

### REQ-BENCH-001-015: B1 — temporary directory isolation

**EARS:** When B1 fetches URLs, the system shall use `tempfile.TemporaryDirectory()` so no fetched content is persisted to `~/mnemosyne/raw/` or any user-visible location.

### REQ-BENCH-001-016: Skip behavior — vault below threshold

**EARS:** While the page count under the wiki root is below 500, the system shall skip B4, B5, and B6 with a clear `SKIP` message instructing the operator to run the large-vault fixture generator.

### REQ-BENCH-001-017: Harness verification

**EARS:** When the harness verification check runs, the system shall confirm that fixture generators produce the expected file counts, that cleanup leaves zero fixture files behind, and that the result recorder appends a syntactically valid Markdown row to `BENCHMARK_RESULTS.md`.

## Risks

| Risk ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-BENCH-001-001 | Fixture pollution of real wiki | High | Strict naming convention `entity_NNNN.md` / `source_NNNN.md`; cleanup uses literal glob match; REQ-BENCH-001-014 forbids touching non-matching files. |
| R-BENCH-001-002 | LLM cost from accidental B2 runs | Medium | B2 is gated on explicit API key presence; uses small synthetic 300-word inputs; total cost per run bounded by 5 × short-doc inference. |
| R-BENCH-001-003 | Network flakiness inflates B1 timings | Medium | Use stable PDF URLs from arXiv; record raw per-URL timing in stderr for diagnosis; document re-run policy in BENCHMARK_GUIDE.md. |
| R-BENCH-001-004 | Threshold defaults drift from SPEC criteria | Medium | Defaults are pinned in this SPEC (URL>30, LLM>60, status>1, lint>2, rebuild>5) and must match SPEC-ARCH-ASYNC-001 Benchmark Criteria; any change requires SPEC update. |
| R-BENCH-001-005 | API key leak via shell history | Medium | Script reads keys from environment only; never echoes key contents; never writes keys to `BENCHMARK_RESULTS.md`. |
| R-BENCH-001-006 | Synthetic fixture is unrepresentative of real workload | Low | Document fixture characteristics in BENCHMARK_RESULTS.md notes; if a downstream SPEC fails on real data despite passing benchmarks, fixture is revised in a follow-up SPEC. |

## Suggested Task Breakdown

| Task ID | Owner Role | Description | Verification |
|---|---|---|---|
| SPEC-BENCH-001-T1 | Test Architect | Author fixture generation scripts: `scripts/bench/gen_large_vault.py` (500 entity + 200 source pages) and `scripts/bench/gen_llm_batch.sh` (5 synthetic files). Author cleanup script `scripts/bench/clean_fixtures.sh`. | Running each generator produces the expected file counts; cleanup removes only fixture files. |
| SPEC-BENCH-001-T2 | Implementer | Extend `benchmark_async.sh` with B2 (LLM batch), B4 (wiki status), B5 (wiki lint at scale), B6 (wiki rebuild dry-run). Add threshold env-var support. Replace abstract URLs in B1 with PDF URLs. Preserve existing B1 behavior shape. | Manual run executes all sections; SKIP messages appear correctly when prerequisites are missing. |
| SPEC-BENCH-001-T3 | Implementer | Implement result recording: append `BENCHMARK_RESULTS.md` row per run with timestamp, all measured values, thresholds, pass/fail status, and decision-matrix conclusion. | After a run, `BENCHMARK_RESULTS.md` contains a new dated section with all six rows (B1, B2, B4, B5, B6, plus decision). |
| SPEC-BENCH-001-T4 | Test Architect | Harness verification: dry-run the full harness end-to-end, confirm fixture isolation by diffing wiki root before and after a run, confirm cleanup completeness. Document the procedure in BENCHMARK_GUIDE.md. | Verification log attached to PR; no non-fixture wiki files modified during run. |

## Verification Commands

### Fixture verification
```bash
# Generate fixtures
python3 scripts/bench/gen_large_vault.py
bash scripts/bench/gen_llm_batch.sh

# Verify counts
find ~/mnemosyne/wiki -name "entity_[0-9]*.md" | wc -l   # expect 500
find ~/mnemosyne/wiki -name "source_[0-9]*.md" | wc -l   # expect 200
ls /tmp/bench_llm_*.txt | wc -l                          # expect 5

# Cleanup
bash scripts/bench/clean_fixtures.sh

# Verify cleanup
find ~/mnemosyne/wiki -name "entity_[0-9]*.md" | wc -l   # expect 0
find ~/mnemosyne/wiki -name "source_[0-9]*.md" | wc -l   # expect 0
ls /tmp/bench_llm_*.txt 2>/dev/null | wc -l              # expect 0
```

### Harness execution
```bash
# Default thresholds
bash benchmark_async.sh

# Custom thresholds
THRESHOLD_URL=15 THRESHOLD_LLM=30 bash benchmark_async.sh

# Without LLM key — B2 must skip cleanly
unset ANTHROPIC_API_KEY OPENAI_API_KEY
bash benchmark_async.sh
```

### Result recording verification
```bash
# After a run
tail -30 .moon-cell/docs/BENCHMARK_RESULTS.md
# Expect: timestamped section with B1, B2, B4, B5, B6 rows and decision matrix
```

### Isolation verification
```bash
# Snapshot before
find ~/mnemosyne/wiki -name "*.md" ! -name "entity_[0-9]*.md" ! -name "source_[0-9]*.md" -exec md5sum {} \; | sort > /tmp/wiki_before.md5

# Run benchmark
bash benchmark_async.sh

# Snapshot after
find ~/mnemosyne/wiki -name "*.md" ! -name "entity_[0-9]*.md" ! -name "source_[0-9]*.md" -exec md5sum {} \; | sort > /tmp/wiki_after.md5

# Verify no non-fixture file changed
diff /tmp/wiki_before.md5 /tmp/wiki_after.md5
# Expect: no output (zero changes)
```

### Static checks (T2/T3 implementation phase)
```bash
shellcheck benchmark_async.sh scripts/bench/*.sh
python -m ruff check scripts/bench/
git diff --check
```

## Definition of Done

| ID | Check | Required Result |
|---|---|---|
| DOD-SPEC-BENCH-001-001 | Fixture scripts (T1) | `gen_large_vault.py`, `gen_llm_batch.sh`, `clean_fixtures.sh` exist and produce/remove the documented file counts. |
| DOD-SPEC-BENCH-001-002 | Extended harness (T2) | `benchmark_async.sh` runs B1, B2, B4, B5, B6 sections; threshold env vars override defaults; B2 skips cleanly without API key; B4/B5/B6 skip cleanly when vault has fewer than 500 pages. |
| DOD-SPEC-BENCH-001-003 | Result recording (T3) | Every run appends a timestamped, machine-parseable section to `BENCHMARK_RESULTS.md` containing all measured values, thresholds, pass/fail per benchmark, and a decision-matrix verdict naming the unblocked SPECs. |
| DOD-SPEC-BENCH-001-004 | Verification (T4) | End-to-end dry-run executed; non-fixture wiki files unchanged (verified via md5 diff); cleanup leaves zero fixture residue; procedure documented in `BENCHMARK_GUIDE.md`. |
| DOD-SPEC-BENCH-001-005 | Static checks | shellcheck on all shell scripts; ruff on Python fixture generators; `git diff --check` clean. |
| DOD-SPEC-BENCH-001-006 | Docs/harness | `BENCHMARK_GUIDE.md` updated to reference the fixture scripts, threshold env vars, and the result-recording file; `MANIFEST.md` and `CHANGELOG.md` updated; `FOLLOW-UP-CANDIDATES.md` notes that SPEC-ARCH-ASYNC-001 T3 and SPEC-WIKI-008 T1 are now decidable. |
| DOD-SPEC-BENCH-001-007 | No product-code change | `git diff mnemosyne/` is empty; this SPEC is harness-only per NG-BENCH-001-006. |

## Notes

- This SPEC produces **evidence**, not implementation. Its successful completion does not
  imply that SPEC-ARCH-ASYNC-001 T3 or SPEC-WIKI-008 T1 will be promoted; it only ensures
  those SPECs can now be **decided** based on measurement rather than speculation.
- The `LLMWikiMaintainer` class (not `LLMWiki`) is the canonical wiki entry point per
  `mnemosyne/wiki/llm_wiki.py`. The existing benchmark script already uses the correct
  symbol; T2 must preserve this.
- `URLFetcher.fetch()` returns a `Path`; sizes are obtained via `saved.stat().st_size`.
  T2 must keep this contract intact.
- Thresholds match SPEC-ARCH-ASYNC-001 Benchmark Criteria exactly: URL >30s, LLM >60s.
  Wiki thresholds (status >1s, lint >2s, rebuild >5s) match BENCHMARK_GUIDE.md Part 2.
- PDF URLs (2-10s each) replace the previously CDN-cached arXiv abstract URLs (<0.1s each)
  to give B1 a realistic chance of crossing the 30s threshold.
