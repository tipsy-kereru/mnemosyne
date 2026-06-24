#!/usr/bin/env bash
# Benchmark harness for the mnemosyne PyOxidizer binary (AC6 + AC7).
#
# AC6: distribution size <= 100 MB (binary + lib/ + companion dirs). Measured
#   as the full footprint because PyOxidizer 0.24 cannot collapse lib/ into
#   the binary. Reclassified advisory via PM Amendment in ISSUE-0008; the
#   path to <=100 MB is ISSUE-0009's PyOxidizer 0.4x + CPython 3.12 upgrade.
# AC7: cold-start `mnemosyne --help` <= 300 ms wall-clock (median of 5 runs).
#
# Thresholds (NFR §7) are goals for ISSUE-0008 on linux-x86_64 dev hardware.
# If the host cannot meet 300 ms, the measured value + analysis is recorded
# rather than failing the build — cross-platform perf tuning is PACKAGE-D.
#
# Usage:
#   scripts/bench_binary.sh [path/to/mnemosyne]
#
# Output: machine-parseable lines:
#   binary_bytes=<n>            (top-level executable only)
#   lib_bytes=<n>               (extension modules, filesystem fallback)
#   companion_bytes=<n>         (jsonschema_specifications + referencing)
#   size_bytes=<n>              (full distribution footprint)
#   size_status=ok|over_budget
#   cold_start_us_median=<n>
#   cold_start_status=ok|over_goal
#
# Exit code: 0 always (AC6 reclassified advisory; AC7 informational).
set -euo pipefail

BINARY="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build/mnemosyne}"
RUNS="${BENCH_RUNS:-5}"

err() { printf 'bench_binary.sh: ERROR: %s\n' "$*" >&2; }

if [[ ! -x "${BINARY}" ]]; then
    err "binary not found or not executable: ${BINARY}"
    err "(build it first: scripts/build_binary.sh)"
    exit 2
fi

# ---- AC6: size -------------------------------------------------------------
# Measure the full distribution footprint (binary + lib/ + filesystem-shipped
# companion dirs) since PyOxidizer 0.24 cannot collapse lib/ into the binary.
# Companion dirs (jsonschema_specifications, referencing) are required at
# runtime for the frozen-import hazard workaround (see BINARY_BUILD.md).
binary_bytes="$(stat -c %s "${BINARY}")"
binary_mb="$(awk -v b="${binary_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}')"
dist_root="$(dirname "${BINARY}")"
lib_bytes=0
[[ -d "${dist_root}/lib" ]] && lib_bytes="$(du -sb "${dist_root}/lib" | cut -f1)"
companion_bytes=0
for pkg in jsonschema_specifications referencing; do
    [[ -d "${dist_root}/${pkg}" ]] && companion_bytes=$((companion_bytes + $(du -sb "${dist_root}/${pkg}" | cut -f1)))
done
size_bytes=$((binary_bytes + lib_bytes + companion_bytes))
size_mb="$(awk -v b="${size_bytes}" 'BEGIN{printf "%.1f", b/1024/1024}')"
size_limit=$((100 * 1024 * 1024))
if (( size_bytes <= size_limit )); then
    size_status="ok"
else
    size_status="over_budget"
fi
printf 'binary_bytes=%s\n' "${binary_bytes}"
printf 'binary_mb=%.1f\n' "${binary_mb}"
printf 'lib_bytes=%s\n' "${lib_bytes}"
printf 'companion_bytes=%s\n' "${companion_bytes}"
printf 'size_bytes=%s\n' "${size_bytes}"
printf 'size_mb=%.1f\n' "${size_mb}"
printf 'size_status=%s\n' "${size_status}"

# ---- AC7: cold-start --help (median of RUNS) -------------------------------
# Use python3 for microsecond timing (date +%s%N is portable enough on linux).
# `--help` exercises only the frozen-import bootstrap; no DB / network.
timing_log="$(mktemp)"
trap 'rm -f "${timing_log}"' EXIT

for _ in $(seq 1 "${RUNS}"); do
    BENCH_BINARY="${BINARY}" python3 - <<'PY' >>"${timing_log}"
import os
import subprocess
import sys
import time

binary = os.environ["BENCH_BINARY"]
t0 = time.perf_counter_ns()
rc = subprocess.run([binary, "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
t1 = time.perf_counter_ns()
if rc != 0:
    sys.stderr.write("bench_binary.sh: --help exited {}\n".format(rc))
    sys.exit(1)
print(t1 - t0)
PY
done

median_us="$(python3 - "${timing_log}" <<'PY'
import statistics
import sys
with open(sys.argv[1]) as f:
    samples = [int(line) for line in f if line.strip()]
print(int(statistics.median(samples) // 1000))
PY
)"
printf 'cold_start_us_median=%s\n' "${median_us}"
printf 'cold_start_runs=%s\n' "${RUNS}"
if (( median_us <= 300 * 1000 )); then
    cold_status="ok"
else
    cold_status="over_goal"
fi
printf 'cold_start_status=%s\n' "${cold_status}"

# ---- Verdict ---------------------------------------------------------------
# AC6 was reclassified advisory via the PM Amendment in ISSUE-0008: on
# PyOxidizer 0.24 + CPython 3.10 the full distribution footprint (binary +
# lib/ + companion dirs) is ~164 MB, and the budget reduction is owned by
# ISSUE-0009 (PyOxidizer 0.4x + CPython 3.12 upgrade collapses lib/ into the
# binary). We log size_status=over_budget as a warning rather than failing
# the bench, so AC7 (cold-start) results are still reported. The skip is
# enforced in tests/test_binary_smoke.py::test_binary_size_within_budget.
# AC7 is an informational goal.
if [[ "${size_status}" != "ok" ]]; then
    err "AC6 ADVISORY: size ${size_mb} MB exceeds 100 MB budget (documented deviation; see BINARY_BUILD.md)"
fi
if [[ "${cold_status}" != "ok" ]]; then
    err "AC7 ADVISORY: cold-start ${median_us}us exceeds 300ms goal (informational, not a gate)"
fi
exit 0
