# Quality Gates

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-04-28 18:43:18 NZST

## Gate Definitions

### QG-001: Pre-Commit Quality Gate

Runs before every commit. Must pass with zero errors.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| mypy | `python3 -m mypy --ignore-missing-imports mnemosyne/` | 0 errors | Yes |
| ruff lint | `python3 -m ruff check mnemosyne/ tests/` | 0 violations | Yes |
| pytest | `python3 -m pytest --tb=short -q` | All pass | Yes |
| coverage | `python3 -m pytest --cov=mnemosyne --cov-report=term-missing` | >= 80% | Warning |

### QG-002: Pre-Release Quality Gate

Runs before version bump or PR creation.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| QG-001 | (all above) | All pass | Yes |
| jest | `cd joplin-plugin/knowledge-graph && npx jest` | All pass | Yes |
| import test | `python3 -c "import mnemosyne; print(mnemosyne.__version__)"` | Success | Yes |
| CLI test | `python3 -m mnemosyne --version` | Success | Yes |

### QG-003: Architecture Change Gate

Runs when modifying core architecture (graph/, extraction/, pyproject.toml).

| Check | Description | Blocking |
|---|---|---|
| Regression test | All existing 295 tests still pass | Yes |
| No breaking changes | Public API signatures unchanged or versioned | Yes |
| Spec coverage | Change traceable to SPEC requirement or documented decision | Warning |
