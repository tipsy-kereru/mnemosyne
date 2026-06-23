# longdoc benchmark fixtures

Only small fixtures are committed here. Large fixtures (50-page PDF,
100k-token markdown) are generated at runtime by
`scripts/bench/longdoc_bench.py` into a temp dir to keep the repo lean.

- `one_page.pdf` — ~1 KiB single-page PDF used by the smoke test
  (`python scripts/bench/longdoc_bench.py --smoke`) and by the fuzz tests.

The full benchmark is gated behind `MNEMOSYNE_RUN_BENCHMARKS=1`; without it
the script prints a skip-reason and exits 0.
