#!/usr/bin/env bash
# Remove benchmark fixture files created by gen_large_vault.py and gen_llm_batch.sh.
# Only removes files matching the fixture naming convention:
#   entity_NNNN.md, source_NNNN.md under MNEMOSYNE_WIKI_ROOT
#   /tmp/bench_llm_*.txt
#
# Real wiki pages are never touched.
#
# REQ-BENCH-001-003 / SPEC-BENCH-001-T1
set -euo pipefail

WIKI_ROOT="${MNEMOSYNE_WIKI_ROOT:-${HOME}/mnemosyne/wiki}"

entity_count=0
source_count=0
llm_count=0

if [[ -d "$WIKI_ROOT" ]]; then
    while IFS= read -r f; do
        rm -f "$f"
        (( entity_count++ )) || true
    done < <(find "$WIKI_ROOT" -name "entity_[0-9]*.md" 2>/dev/null)

    while IFS= read -r f; do
        rm -f "$f"
        (( source_count++ )) || true
    done < <(find "$WIKI_ROOT" -name "source_[0-9]*.md" 2>/dev/null)

    # Remove empty fixture directories (but not the wiki root itself or non-empty dirs)
    find "$WIKI_ROOT/entities" -type d -empty -delete 2>/dev/null || true
    find "$WIKI_ROOT/sources" -type d -empty -delete 2>/dev/null || true
fi

while IFS= read -r f; do
    rm -f "$f"
    (( llm_count++ )) || true
done < <(ls /tmp/bench_llm_*.txt 2>/dev/null || true)

echo "Removed ${entity_count} entity fixture pages"
echo "Removed ${source_count} source fixture pages"
echo "Removed ${llm_count} LLM batch fixture files"
echo "Cleanup complete."
