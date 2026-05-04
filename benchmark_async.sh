#!/usr/bin/env bash
# benchmark_async.sh — SPEC-ARCH-ASYNC-001 T3 gate check
# 결과가 임계값을 초과하면 async 구현(T3)이 정당화됩니다.
set -euo pipefail

PYTHON=${PYTHON:-python3}
THRESHOLD_URL=30   # seconds — 10 URLs serial fetch
THRESHOLD_WIKI=2   # seconds — wiki lint

PASS=0
FAIL=0

hr() { printf '%0.s─' {1..60}; echo; }

banner() {
    echo
    hr
    echo "  $1"
    hr
}

result() {
    local label=$1 elapsed=$2 threshold=$3
    if (( $(echo "$elapsed > $threshold" | bc -l) )); then
        echo "  ✅ PASS  ${elapsed}s > ${threshold}s  →  async 정당화"
        PASS=$((PASS + 1))
    else
        echo "  ❌ MISS  ${elapsed}s ≤ ${threshold}s  →  async 효과 미미"
        FAIL=$((FAIL + 1))
    fi
}

# ── Benchmark 1: URL serial fetch (10 URLs) ───────────────────────────────────
banner "Benchmark 1: URL 직렬 fetch × 10  (임계값: >${THRESHOLD_URL}s)"

URLS=(
    "https://arxiv.org/abs/2509.15464"
    "https://arxiv.org/abs/2501.13956"
    "https://arxiv.org/abs/2403.04782"
    "https://arxiv.org/abs/2506.06367"
    "https://arxiv.org/abs/2402.11542"
    "https://docs.python.org/3/library/asyncio-task.html"
    "https://docs.python.org/3/library/asyncio-sync.html"
    "https://www.python-httpx.org/async/"
    "https://aiosqlite.omnilib.dev/en/stable/api.html"
    "https://realpython.com/async-io-python/"
)

B1_ELAPSED=$($PYTHON - "${URLS[@]}" <<'PYEOF'
import sys, time, tempfile
from pathlib import Path
from mnemosyne.ingest.url_fetcher import URLFetcher

urls = sys.argv[1:]
fetcher = URLFetcher(timeout=20)
t0 = time.perf_counter()
with tempfile.TemporaryDirectory() as tmp:
    raw_dir = Path(tmp)
    for url in urls:
        t1 = time.perf_counter()
        try:
            saved: Path = fetcher.fetch(url, raw_dir=raw_dir)
            chars = saved.stat().st_size
            status = f"{chars:>7} bytes"
        except Exception as e:
            status = f"ERROR: {e}"
        elapsed = time.perf_counter() - t1
        print(f"  {elapsed:5.1f}s  {status}  {url[:55]}", file=sys.stderr)
total = time.perf_counter() - t0
print(f"{total:.2f}")
PYEOF
)

echo
result "URL fetch ×10" "$B1_ELAPSED" "$THRESHOLD_URL"

# ── Benchmark 2: wiki lint ─────────────────────────────────────────────────────
banner "Benchmark 2: wiki lint  (임계값: >${THRESHOLD_WIKI}s)"

WIKI_ROOT="${MNEMOSYNE_WIKI_ROOT:-${HOME}/mnemosyne/wiki}"
PAGE_COUNT=$(find "$WIKI_ROOT" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
PAGE_COUNT=${PAGE_COUNT:-0}
echo "  Wiki 경로: $WIKI_ROOT"
echo "  페이지 수: $PAGE_COUNT"

if [[ "$PAGE_COUNT" -lt 100 ]]; then
    echo "  ⚠️  SKIP  페이지가 ${PAGE_COUNT}개뿐 — 500개 이상일 때 의미 있는 측정 가능"
    echo "  (현재 vault 크기로는 filesystem async 필요성 없음)"
else
    B2_ELAPSED=$($PYTHON - "$WIKI_ROOT" <<'PYEOF'
import sys, time
from mnemosyne.wiki.llm_wiki import LLMWikiMaintainer

wiki = LLMWikiMaintainer(sys.argv[1])
t0 = time.perf_counter()
wiki.lint()
total = time.perf_counter() - t0
print(f"{total:.2f}")
PYEOF
    )
    result "wiki lint" "$B2_ELAPSED" "$THRESHOLD_WIKI"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
banner "결과 요약"
echo "  통과: $PASS / 실패(임계 미달): $FAIL"
echo
if [[ "$PASS" -ge 1 ]]; then
    echo "  → T3 구현 시작 가능 (임계값 초과 항목 존재)"
else
    echo "  → T3 보류 권장 (모든 항목이 임계값 미달)"
fi
hr
