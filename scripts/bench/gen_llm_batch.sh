#!/usr/bin/env bash
# Generate synthetic LLM batch fixture files for benchmark B2.
# Produces 5 text files at /tmp/bench_llm_1.txt .. /tmp/bench_llm_5.txt
# each approximately 300 words.
#
# REQ-BENCH-001-002 / SPEC-BENCH-001-T1
set -euo pipefail

WORDS=(
    knowledge graph entity relation temporal async python sqlite wiki mnemosyne
    extraction pipeline ingest domain coding legal daily function class module
    api bug feature test dependency statute clause case party obligation deadline
    contract habit preference note person place event schema source channel scope
    session memory retrieval vector embedding similarity search query filter
)

generate_doc() {
    local n=$1
    local topic=${WORDS[$((n % ${#WORDS[@]}))]}
    {
        printf "Document %d: Analysis of %s systems and their integration patterns.\n\n" "$n" "$topic"
        local count=0
        while (( count < 270 )); do
            local idx=$(( RANDOM % ${#WORDS[@]} ))
            printf "%s " "${WORDS[$idx]}"
            (( count++ )) || true
        done
        printf "\n\nConclusion: The %s system demonstrates key properties relevant to knowledge graph construction.\n" "$topic"
    }
}

for i in $(seq 1 5); do
    generate_doc "$i" > "/tmp/bench_llm_${i}.txt"
    wc -w "/tmp/bench_llm_${i}.txt" | awk '{printf "  bench_llm_%d.txt: ~%d words\n", '"$i"', $1}'
done

echo "Generated 5 LLM batch fixture files at /tmp/bench_llm_*.txt"
