#!/usr/bin/env bash
# benchmark_async.sh — SPEC-BENCH-001 benchmark harness
#
# Runs B1–B6 gate checks and records results to .moon-cell/docs/BENCHMARK_RESULTS.md.
# Results exceeding thresholds unblock downstream SPEC implementation:
#   B1 OR B2 PASS  → SPEC-ARCH-ASYNC-001 T3 (async URL fetch / LLM ingest)
#   B4/B5/B6 PASS  → SPEC-WIKI-008 T1 (incremental wiki index optimization)
#
# Threshold env vars (override defaults):
#   THRESHOLD_URL          — B1 URL serial fetch, default 30s
#   THRESHOLD_LLM          — B2 LLM batch ingest, default 60s
#   THRESHOLD_WIKI_STATUS  — B4 wiki status, default 1s
#   THRESHOLD_WIKI_LINT    — B5 wiki lint, default 2s
#   THRESHOLD_WIKI_REBUILD — B6 wiki rebuild dry-run, default 5s
#
# REQ-BENCH-001-001 through REQ-BENCH-001-017 / SPEC-BENCH-001 T2+T3
set -euo pipefail

PYTHON=${PYTHON:-uv run python}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_FILE="${SCRIPT_DIR}/.moon-cell/docs/BENCHMARK_RESULTS.md"

# Thresholds (REQ-BENCH-001-011)
THRESHOLD_URL=${THRESHOLD_URL:-30}
THRESHOLD_LLM=${THRESHOLD_LLM:-60}
THRESHOLD_WIKI_STATUS=${THRESHOLD_WIKI_STATUS:-1}
THRESHOLD_WIKI_LINT=${THRESHOLD_WIKI_LINT:-2}
THRESHOLD_WIKI_REBUILD=${THRESHOLD_WIKI_REBUILD:-5}

WIKI_ROOT="${MNEMOSYNE_WIKI_ROOT:-${HOME}/mnemosyne/wiki}"

# Tracking state
PASS=0
MISS=0
SKIP=0
ASYNC_PASS=0   # B1 or B2
WIKI_PASS=0    # B4 or B5 or B6

# Per-benchmark recorded values (for result recording)
B1_VAL="skipped"; B1_STATUS="SKIP"
B2_VAL="skipped"; B2_STATUS="SKIP"
B4_VAL="skipped"; B4_STATUS="SKIP"
B5_VAL="skipped"; B5_STATUS="SKIP"
B6_VAL="skipped"; B6_STATUS="SKIP"

hr() { printf '%0.s─' {1..70}; echo; }

banner() {
    echo
    hr
    echo "  $1"
    hr
}

# REQ-BENCH-001-010: compare elapsed against threshold
result() {
    local label=$1 elapsed=$2 threshold=$3
    if (( $(echo "$elapsed > $threshold" | bc -l) )); then
        echo "  ✅ PASS  ${elapsed}s > ${threshold}s  →  implementation justified"
        PASS=$((PASS + 1))
        _RESULT="PASS"
    else
        echo "  ❌ MISS  ${elapsed}s ≤ ${threshold}s  →  implementation not yet justified"
        MISS=$((MISS + 1))
        _RESULT="MISS"
    fi
}

# ── Benchmark 1: URL serial fetch — PDF URLs ──────────────────────────────────
# REQ-BENCH-001-004 / REQ-BENCH-001-015
banner "Benchmark B1: URL serial fetch × 10 PDF URLs  (threshold: >${THRESHOLD_URL}s)"

PDF_URLS=(
    "https://arxiv.org/pdf/2509.15464"
    "https://arxiv.org/pdf/2501.13956"
    "https://arxiv.org/pdf/2403.04782"
    "https://arxiv.org/pdf/2506.06367"
    "https://arxiv.org/pdf/2402.11542"
    "https://arxiv.org/pdf/2310.03744"
    "https://arxiv.org/pdf/2402.06196"
    "https://arxiv.org/pdf/2312.10997"
    "https://arxiv.org/pdf/2305.10601"
    "https://arxiv.org/pdf/2404.16130"
)

B1_ELAPSED=$($PYTHON - "${PDF_URLS[@]}" <<'PYEOF'
import sys, time, tempfile
from pathlib import Path
from mnemosyne.ingest.url_fetcher import URLFetcher

urls = sys.argv[1:]
fetcher = URLFetcher(timeout=30)
t0 = time.perf_counter()
with tempfile.TemporaryDirectory() as tmp:
    raw_dir = Path(tmp)
    for url in urls:
        t1 = time.perf_counter()
        try:
            saved: Path = fetcher.fetch(url, raw_dir=raw_dir)
            size = saved.stat().st_size
            status = f"{size:>8} bytes"
        except Exception as e:
            status = f"ERROR: {e}"
        elapsed = time.perf_counter() - t1
        print(f"  {elapsed:5.1f}s  {status}  {url[:60]}", file=sys.stderr)
total = time.perf_counter() - t0
print(f"{total:.2f}")
PYEOF
)

echo
result "URL fetch ×10 PDF" "$B1_ELAPSED" "$THRESHOLD_URL"
B1_STATUS=$_RESULT
B1_VAL="$B1_ELAPSED"
if [[ "$B1_STATUS" == "PASS" ]]; then ASYNC_PASS=1; fi

# ── Benchmark B2: LLM batch ingest ───────────────────────────────────────────
# REQ-BENCH-001-005 / REQ-BENCH-001-006
banner "Benchmark B2: LLM batch ingest × 5 files  (threshold: >${THRESHOLD_LLM}s)"

if [[ -z "${ANTHROPIC_API_KEY:-}${OPENAI_API_KEY:-}${Z_AI_API_KEY:-}" ]]; then
    echo "  ⚠️  SKIP  No API key set (ANTHROPIC_API_KEY, OPENAI_API_KEY, or Z_AI_API_KEY required)"
    echo "  Run:  bash scripts/bench/gen_llm_batch.sh  then set an API key and re-run"
    SKIP=$((SKIP + 1))
    B2_STATUS="SKIP"
else
    echo "  Generating synthetic batch files..."
    bash "${SCRIPT_DIR}/scripts/bench/gen_llm_batch.sh" 2>/dev/null

    B2_START=$(date +%s%N)
    for i in 1 2 3 4 5; do
        uv run mnemosyne add /tmp/bench_llm_${i}.txt --domain coding 2>&1 | sed 's/^/  /'
    done
    B2_ELAPSED_RAW=$(( $(date +%s%N) - B2_START ))
    B2_ELAPSED=$(echo "scale=2; $B2_ELAPSED_RAW / 1000000000" | bc)

    rm -f /tmp/bench_llm_{1..5}.txt

    echo
    result "LLM batch ×5" "$B2_ELAPSED" "$THRESHOLD_LLM"
    B2_STATUS=$_RESULT
    B2_VAL="$B2_ELAPSED"
    if [[ "$B2_STATUS" == "PASS" ]]; then ASYNC_PASS=1; fi
fi

# ── Page count for B4-B6 gate ─────────────────────────────────────────────────
PAGE_COUNT=$(find "$WIKI_ROOT" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
PAGE_COUNT=${PAGE_COUNT:-0}

# ── Benchmark B4: wiki status at scale ────────────────────────────────────────
# REQ-BENCH-001-007 / REQ-BENCH-001-016
banner "Benchmark B4: wiki status  (threshold: >${THRESHOLD_WIKI_STATUS}s, pages: ${PAGE_COUNT})"

if [[ "$PAGE_COUNT" -lt 500 ]]; then
    echo "  ⚠️  SKIP  ${PAGE_COUNT} pages found — need 500+ for meaningful measurement"
    echo "  Run:  uv run python scripts/bench/gen_large_vault.py  then re-run"
    SKIP=$((SKIP + 1))
    B4_STATUS="SKIP"
else
    B4_START=$(date +%s%N)
    uv run mnemosyne wiki status --wiki-root "$WIKI_ROOT" > /dev/null 2>&1
    B4_ELAPSED_RAW=$(( $(date +%s%N) - B4_START ))
    B4_ELAPSED=$(echo "scale=2; $B4_ELAPSED_RAW / 1000000000" | bc)

    echo
    result "wiki status (${PAGE_COUNT} pages)" "$B4_ELAPSED" "$THRESHOLD_WIKI_STATUS"
    B4_STATUS=$_RESULT
    B4_VAL="$B4_ELAPSED"
    if [[ "$B4_STATUS" == "PASS" ]]; then WIKI_PASS=1; fi
fi

# ── Benchmark B5: wiki lint at scale ──────────────────────────────────────────
# REQ-BENCH-001-008 / REQ-BENCH-001-016
banner "Benchmark B5: wiki lint  (threshold: >${THRESHOLD_WIKI_LINT}s, pages: ${PAGE_COUNT})"

if [[ "$PAGE_COUNT" -lt 500 ]]; then
    echo "  ⚠️  SKIP  ${PAGE_COUNT} pages found — need 500+ for meaningful measurement"
    SKIP=$((SKIP + 1))
    B5_STATUS="SKIP"
else
    B5_START=$(date +%s%N)
    uv run mnemosyne wiki lint --wiki-root "$WIKI_ROOT" > /dev/null 2>&1 || true
    B5_ELAPSED_RAW=$(( $(date +%s%N) - B5_START ))
    B5_ELAPSED=$(echo "scale=2; $B5_ELAPSED_RAW / 1000000000" | bc)

    echo
    result "wiki lint (${PAGE_COUNT} pages)" "$B5_ELAPSED" "$THRESHOLD_WIKI_LINT"
    B5_STATUS=$_RESULT
    B5_VAL="$B5_ELAPSED"
    if [[ "$B5_STATUS" == "PASS" ]]; then WIKI_PASS=1; fi
fi

# ── Benchmark B6: wiki rebuild dry-run at scale ───────────────────────────────
# REQ-BENCH-001-009 / REQ-BENCH-001-016
banner "Benchmark B6: wiki rebuild --dry-run  (threshold: >${THRESHOLD_WIKI_REBUILD}s, pages: ${PAGE_COUNT})"

if [[ "$PAGE_COUNT" -lt 500 ]]; then
    echo "  ⚠️  SKIP  ${PAGE_COUNT} pages found — need 500+ for meaningful measurement"
    SKIP=$((SKIP + 1))
    B6_STATUS="SKIP"
else
    B6_START=$(date +%s%N)
    uv run mnemosyne wiki rebuild --wiki-root "$WIKI_ROOT" --dry-run > /dev/null 2>&1 || true
    B6_ELAPSED_RAW=$(( $(date +%s%N) - B6_START ))
    B6_ELAPSED=$(echo "scale=2; $B6_ELAPSED_RAW / 1000000000" | bc)

    echo
    result "wiki rebuild dry-run (${PAGE_COUNT} pages)" "$B6_ELAPSED" "$THRESHOLD_WIKI_REBUILD"
    B6_STATUS=$_RESULT
    B6_VAL="$B6_ELAPSED"
    if [[ "$B6_STATUS" == "PASS" ]]; then WIKI_PASS=1; fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
banner "Summary"
echo "  PASS: $PASS  |  MISS: $MISS  |  SKIP: $SKIP"

# ── Decision matrix (REQ-BENCH-001-013) ──────────────────────────────────────
echo
echo "  Decision Matrix:"
echo "  ┌─────────────────────────────────────────────────────────────────┐"
if [[ "$ASYNC_PASS" -ge 1 ]]; then
    echo "  │  ✅ SPEC-ARCH-ASYNC-001 T3  UNBLOCKED  (B1 or B2 threshold met) │"
    ASYNC_DECISION="UNBLOCKED"
else
    echo "  │  ⏸  SPEC-ARCH-ASYNC-001 T3  DEFERRED   (B1 and B2 below threshold)│"
    ASYNC_DECISION="DEFERRED"
fi
if [[ "$WIKI_PASS" -ge 1 ]]; then
    echo "  │  ✅ SPEC-WIKI-008 T1        UNBLOCKED  (B4/B5/B6 threshold met)  │"
    WIKI_DECISION="UNBLOCKED"
else
    echo "  │  ⏸  SPEC-WIKI-008 T1        DEFERRED   (B4/B5/B6 below threshold) │"
    WIKI_DECISION="DEFERRED"
fi
echo "  └─────────────────────────────────────────────────────────────────┘"

# ── Result recording (REQ-BENCH-001-012) ─────────────────────────────────────
RUN_TS=$(TZ=Pacific/Auckland date '+%Y-%m-%d %H:%M:%S %Z')

mkdir -p "$(dirname "$RESULTS_FILE")"

# Create file with header if it doesn't exist
if [[ ! -f "$RESULTS_FILE" ]]; then
    cat > "$RESULTS_FILE" <<'HEADER'
# Benchmark Results

Generated by `benchmark_async.sh` — SPEC-BENCH-001.
Each run appends a timestamped section.
Thresholds: URL >30s, LLM >60s, wiki status >1s, wiki lint >2s, wiki rebuild >5s.

HEADER
fi

cat >> "$RESULTS_FILE" <<RECORD

## Run: ${RUN_TS}

| Benchmark | Measured | Threshold | Result | Notes |
|---|---|---|---|---|
| B1 URL fetch ×10 (PDF) | ${B1_VAL}s | >${THRESHOLD_URL}s | ${B1_STATUS} | arXiv PDF URLs |
| B2 LLM batch ×5 | ${B2_VAL}s | >${THRESHOLD_LLM}s | ${B2_STATUS} | Requires API key |
| B4 wiki status | ${B4_VAL}s | >${THRESHOLD_WIKI_STATUS}s | ${B4_STATUS} | ${PAGE_COUNT} pages |
| B5 wiki lint | ${B5_VAL}s | >${THRESHOLD_WIKI_LINT}s | ${B5_STATUS} | ${PAGE_COUNT} pages |
| B6 wiki rebuild dry-run | ${B6_VAL}s | >${THRESHOLD_WIKI_REBUILD}s | ${B6_STATUS} | ${PAGE_COUNT} pages |

**Decision:** SPEC-ARCH-ASYNC-001 T3 → ${ASYNC_DECISION} | SPEC-WIKI-008 T1 → ${WIKI_DECISION}

RECORD

echo
echo "  Results recorded → ${RESULTS_FILE}"
hr
