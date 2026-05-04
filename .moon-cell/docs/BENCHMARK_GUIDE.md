# Benchmark Guide

Generated: 2026-05-04 13:28:55 NZST
Updated: 2026-05-04 (SPEC-BENCH-001 harness added)
Source SPECs: SPEC-ARCH-ASYNC-001, SPEC-WIKI-008, SPEC-BENCH-001

This document describes what needs to be measured, how to generate test data,
and what thresholds trigger implementation work.

---

## Quick Start (SPEC-BENCH-001 harness)

The benchmark harness is now scripted. Run order:

```bash
# 1. Generate large-vault fixture (500 entity + 200 source pages)
python3 scripts/bench/gen_large_vault.py

# 2. Run all benchmarks (B1–B6)
bash benchmark_async.sh

# 3. View recorded results
cat .moon-cell/docs/BENCHMARK_RESULTS.md

# 4. Clean up fixtures when done
bash scripts/bench/clean_fixtures.sh
```

Threshold env vars (override defaults without editing the script):
```bash
THRESHOLD_URL=15 THRESHOLD_LLM=30 bash benchmark_async.sh
```

B2 (LLM batch) requires an API key — skip is automatic when no key is set:
```bash
unset ANTHROPIC_API_KEY OPENAI_API_KEY
bash benchmark_async.sh   # B2 skips cleanly
```

Results are appended to `.moon-cell/docs/BENCHMARK_RESULTS.md` after each run.

---

## Fixture Scripts

| Script | Purpose |
|---|---|
| `scripts/bench/gen_large_vault.py` | Generate 500 entity + 200 source pages (`entity_NNNN.md` / `source_NNNN.md`) |
| `scripts/bench/gen_llm_batch.sh` | Generate 5 synthetic text files at `/tmp/bench_llm_*.txt` |
| `scripts/bench/clean_fixtures.sh` | Remove only fixture pages and batch files; real pages untouched |

Fixture pages use the naming convention `entity_NNNN.md` and `source_NNNN.md`
so they are distinguishable from real wiki pages and safe to clean up via the cleanup script.

Verify fixture counts after generation:
```bash
find ~/mnemosyne/wiki -name "entity_[0-9]*.md" | wc -l   # expect 500
find ~/mnemosyne/wiki -name "source_[0-9]*.md" | wc -l   # expect 200
```

Verify cleanup is complete:
```bash
bash scripts/bench/clean_fixtures.sh
find ~/mnemosyne/wiki -name "entity_[0-9]*.md" | wc -l   # expect 0
find ~/mnemosyne/wiki -name "source_[0-9]*.md" | wc -l   # expect 0
```

---

## Overview

Two SPECs are gated on benchmark evidence before implementation can proceed:

| SPEC | What It Unlocks | Gate Condition |
|---|---|---|
| SPEC-ARCH-ASYNC-001 T3 | Async URL fetch + LLM batch ingest | Any one URL/LLM threshold exceeded |
| SPEC-WIKI-008 T1+ | Incremental wiki index optimization | Wiki operations exceed latency thresholds |

Current status (2026-05-04):
- SPEC-ARCH-ASYNC-001: 10 URLs measured at 1.28s total (threshold >30s) — **not met**
- SPEC-WIKI-008: 0 wiki pages — **not measurable yet**

---

## Part 1: SPEC-ARCH-ASYNC-001 — Async I/O

### What needs to exceed threshold

At least one of the following must be true before T3 (implementation) starts:

| Benchmark | Tool | Threshold |
|---|---|---|
| B1: 10 URL serial fetch | `benchmark_async.sh` | **>30s total** |
| B2: 5-file LLM batch ingest | `benchmark_async.sh` (add LLM section) | **>60s total** |
| B3: Wiki lint on large vault | `benchmark_async.sh` | **>2s** (also gated on B4) |

### Why the first run did not pass

- arXiv pages were resolved in <0.1s each — likely cached at network layer or CDN
- Total: 1.28s for 10 URLs

### How to get a meaningful B1 reading

The fetch time depends heavily on the URLs and network conditions.
To get a realistic measurement:

**Option A — Use slower real-world URLs (PDFs, large HTML)**

```bash
# PDF fetches are slower; substitute into benchmark_async.sh URLS array:
"https://arxiv.org/pdf/2509.15464"   # full PDF, not abstract page
"https://arxiv.org/pdf/2501.13956"
"https://arxiv.org/pdf/2403.04782"
"https://arxiv.org/pdf/2506.06367"
"https://arxiv.org/pdf/2402.11542"
```

PDF fetches typically take 2–10s each vs <0.1s for abstract pages.
10 PDFs serially should approach or exceed 30s.

**Option B — Use `mnemosyne add` end-to-end (includes DB write)**

```bash
time mnemosyne add https://arxiv.org/pdf/2509.15464 \
                   https://arxiv.org/pdf/2501.13956 \
                   https://arxiv.org/pdf/2403.04782 \
                   https://arxiv.org/pdf/2506.06367 \
                   https://arxiv.org/pdf/2402.11542 \
                   https://docs.python.org/3/library/asyncio-task.html \
                   https://docs.python.org/3/library/asyncio-sync.html \
                   https://www.python-httpx.org/async/ \
                   https://aiosqlite.omnilib.dev/en/stable/api.html \
                   https://realpython.com/async-io-python/
```

### B2: LLM batch ingest setup (requires API key)

Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, then:

```bash
# Prepare test files (~500-1000 words each for realistic chunking)
for i in $(seq 1 5); do
  python3 -c "
import random, string
words = ['knowledge', 'graph', 'entity', 'relation', 'temporal', 'async',
         'python', 'sqlite', 'wiki', 'mnemosyne', 'extraction', 'pipeline']
text = ' '.join(random.choices(words, k=300))
print(f'Document {$i} about {random.choice(words)} systems.\n\n' + text)
" > /tmp/bench_llm_$i.txt
done

time mnemosyne add /tmp/bench_llm_1.txt \
                   /tmp/bench_llm_2.txt \
                   /tmp/bench_llm_3.txt \
                   /tmp/bench_llm_4.txt \
                   /tmp/bench_llm_5.txt \
                   --domain coding
```

Threshold: >60s total → T3 async implementation justified.

---

## Part 2: SPEC-WIKI-008 — Large Vault Performance

### What needs to exceed threshold

| Benchmark | Operation | Threshold |
|---|---|---|
| B4: `wiki status` | glob all pages, count | **>1s** on 500+ pages |
| B5: `wiki lint` | rglob + read_text per page | **>2s** on 500+ pages |
| B6: `wiki rebuild` | full index rewrite | **>5s** on 500+ pages |

### How to generate a large vault fixture

The wiki page structure is:
```
~/mnemosyne/wiki/
├── entities/{type}/{name}.md
├── sources/{domain}/{slug}.md
└── _index.md
```

**Generate 500 synthetic entity pages:**

```bash
python3 - <<'EOF'
import os
from pathlib import Path

wiki_root = Path.home() / "mnemosyne" / "wiki"
entity_types = ["function", "class", "module", "api", "bug", "feature", "person", "task"]

for i in range(500):
    etype = entity_types[i % len(entity_types)]
    name = f"entity_{i:04d}"
    path = wiki_root / "entities" / etype / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
entity_type: {etype}
entity_name: {name}
scope_id: bench
source_channel: benchmark
generated: "2026-05-04"
---

# {name}

Synthetic benchmark entity of type `{etype}`.

Properties: index={i}, type={etype}

[[entity:{etype}:{name}]]
""")

print(f"Generated {i+1} pages in {wiki_root}/entities/")
EOF
```

**Generate 200 synthetic source pages:**

```bash
python3 - <<'EOF'
from pathlib import Path

wiki_root = Path.home() / "mnemosyne" / "wiki"
domains = ["coding", "daily", "legal"]

for i in range(200):
    domain = domains[i % len(domains)]
    slug = f"source_{i:04d}"
    path = wiki_root / "sources" / domain / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
source: text://bench/{slug}
domain: {domain}
scope_id: bench
source_channel: benchmark
entities_extracted: 3
relations_extracted: 1
---

# {slug}

Synthetic benchmark source document in domain `{domain}`.
""")

print(f"Generated {i+1} source pages in {wiki_root}/sources/")
EOF
```

**Verify page count:**
```bash
find ~/mnemosyne/wiki -name "*.md" | wc -l
# Expected: ~700
```

### Run the vault benchmarks

```bash
# B4: status
time mnemosyne wiki status --wiki-root ~/mnemosyne/wiki

# B5: lint
time mnemosyne wiki lint --wiki-root ~/mnemosyne/wiki

# B6: rebuild (dry-run, no DB required)
time mnemosyne wiki rebuild --wiki-root ~/mnemosyne/wiki --dry-run
```

### Clean up fixture after benchmarking

```bash
# Remove only benchmark-generated pages (keeps real pages)
find ~/mnemosyne/wiki -name "entity_[0-9]*.md" -delete
find ~/mnemosyne/wiki -name "source_[0-9]*.md" -delete
find ~/mnemosyne/wiki/entities -type d -empty -delete
find ~/mnemosyne/wiki/sources -type d -empty -delete
echo "Fixture cleaned."
```

---

## Part 3: Updating benchmark_async.sh

The current `benchmark_async.sh` covers B1 and B3. To add B2 and B4–B6,
extend the script with the following sections after B1:

### B2 section to add (LLM batch ingest)

```bash
# ── Benchmark 2b: LLM batch ingest (5 files) ─────────────────────────────────
banner "Benchmark 2b: LLM batch ingest × 5  (임계값: >${THRESHOLD_LLM:-60}s)"

if [[ -z "${ANTHROPIC_API_KEY:-}${OPENAI_API_KEY:-}" ]]; then
    echo "  ⚠️  SKIP  API key not set (ANTHROPIC_API_KEY or OPENAI_API_KEY required)"
else
    for i in $(seq 1 5); do
        python3 -c "print('Benchmark document $i about knowledge graphs and async IO.' * 50)" \
            > /tmp/bench_llm_$i.txt
    done

    B2B_START=$(date +%s%N)
    mnemosyne add /tmp/bench_llm_{1..5}.txt --domain coding --no-wiki 2>/dev/null
    B2B_ELAPSED=$(echo "scale=2; ($(date +%s%N) - $B2B_START) / 1000000000" | bc)

    rm -f /tmp/bench_llm_{1..5}.txt
    result "LLM batch ×5" "$B2B_ELAPSED" "${THRESHOLD_LLM:-60}"
fi
```

### B4–B6 section to add (large vault)

```bash
# ── Benchmark 3: large vault operations ───────────────────────────────────────
banner "Benchmark 3: wiki ops on ${PAGE_COUNT} pages"

if [[ "$PAGE_COUNT" -lt 500 ]]; then
    echo "  ⚠️  SKIP  <500 pages — generate fixture first (see BENCHMARK_GUIDE.md)"
else
    for op in status lint; do
        T_START=$(date +%s%N)
        mnemosyne wiki $op --wiki-root "$WIKI_ROOT" > /dev/null 2>&1
        T_ELAPSED=$(echo "scale=2; ($(date +%s%N) - $T_START) / 1000000000" | bc)
        echo "  wiki $op: ${T_ELAPSED}s"
    done
fi
```

---

## Decision Matrix

After running benchmarks, use this table to decide next steps:

| Result | Action |
|---|---|
| B1 or B2 exceeded | Promote SPEC-ARCH-ASYNC-001 T3 to active; implement `fetch_async`, `extract_async`, `add_urls_async` |
| B4–B6 exceeded | Promote SPEC-WIKI-008 T1; design incremental index approach |
| None exceeded | Keep both SPECs deferred; re-run when usage patterns change |
| B1 exceeded, B4–B6 not | Implement async network only; no filesystem async needed |

---

## Notes

- Benchmark results should be recorded in `.moon-cell/specs/SPEC-ARCH-ASYNC-001.md`
  under the "Benchmark Criteria" section with actual measured values.
- Re-run benchmarks after any significant change in usage scale
  (e.g., vault grows past 1000 pages, or batch ingest becomes routine).
- `benchmark_async.sh` is the canonical runner; do not rely on ad-hoc timing.
