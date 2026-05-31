# Quality Gates

Generated: 2026-04-28 18:43:18 NZST
Updated: 2026-05-03 17:31:31 NZST

## Gate Definitions

### QG-001: Pre-Commit Quality Gate

Runs before every commit or production-significant code change. Must pass with zero blocking errors.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| mypy | `mypy --ignore-missing-imports mnemosyne/` | 0 errors | Yes |
| ruff lint | `python3 -m ruff check mnemosyne/ tests/` | 0 violations | Yes |
| pytest | `python3 -m pytest --tb=short -q` | All pass | Yes |
| coverage | `python3 -m pytest --cov=mnemosyne --cov-report=term-missing` | >= 80% | Warning |

### QG-002: Pre-Release Quality Gate

Runs before version bump, package publishing, release branch, or PR creation.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| QG-001 | All pre-commit checks above | All pass | Yes |
| jest | `cd joplin-plugin/knowledge-graph && npx jest` | All pass | Yes |
| import test | `python3 -c "import mnemosyne; print(mnemosyne.__version__)"` | Success | Yes |
| CLI test | `python3 -m mnemosyne --version` | Success | Yes |

### QG-003: Architecture Change Gate

Runs when modifying core architecture, graph storage, extraction pipeline, public CLI/API, or package config.

| Check | Description | Blocking |
|---|---|---|
| Regression test | All existing tests pass; current evidence is 413 passed / 2 skipped | Yes |
| No breaking changes | Public API signatures unchanged or versioned | Yes |
| Spec coverage | Change traceable to a SPEC requirement or documented decision | Warning |
| Handoff update | `CONTEXT_HANDOFF.md` updated for multi-session or architecture work | Warning |

### QG-004: Harness Change Gate

Runs when editing `.moon-cell/**` or root/runtime bridge files.

| Check | Description | Blocking |
|---|---|---|
| Source-of-truth preservation | `.moon-cell/` remains canonical | Yes |
| Root bridge confirmation | Root `AGENTS.md`, `CLAUDE.md`, `.cursor/**`, `.claude/**` modified only with explicit confirmation | Yes |
| Manifest refresh | `MANIFEST.md` reflects added/changed harness artifacts | Yes |
| Changelog refresh | `CHANGELOG.md` records harness changes | Yes |
| Handoff refresh | `CONTEXT_HANDOFF.md` records current state and evidence | Yes |

### QG-005: Warning Cleanliness Gate

Runs when warning remediation or timestamp-producing code is modified. This gate is introduced by SPEC-WARN-001.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| Affected warning-as-error subset | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -W error::DeprecationWarning -m pytest tests/test_scope_manager.py tests/test_knowledge_graph_session.py tests/test_pipeline.py tests/test_pipeline_integration.py --tb=short -q` | 0 project-owned deprecation warnings | Yes for SPEC-WARN-001 |
| Static deprecated timestamp search | `grep -R "datetime.utcnow" -n mnemosyne tests --exclude-dir=__pycache__` | No matches in `mnemosyne/` | Yes for SPEC-WARN-001 |
| Full warning summary | `python3 -m pytest --tb=short -q` | Target: 0 warnings; minimum: 0 project-owned warnings | Yes for SPEC-WARN-001 |

### QG-006: LLM Wiki / Graph Consistency Gate

Runs when modifying `mnemosyne/wiki/**`, ingestion-to-wiki behavior, graph merge semantics, or `mnemosyne wiki` CLI commands. Introduced by SPEC-WIKI-001.

| Check | Command | Threshold | Blocking |
|---|---|---|---|
| Wiki focused tests | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` | All pass | Yes for SPEC-WIKI-001 |
| Full tests | `pytest -q` | All pass | Yes |
| Static checks | `ruff check mnemosyne tests && mypy mnemosyne` | 0 blocking issues | Yes |
| Diff hygiene | `git diff --check` | No whitespace errors | Yes |
| CLI smoke | `python -m mnemosyne wiki status|lint|rebuild` against temp roots | status/lint/rebuild succeed | Yes for SPEC-WIKI-001 |

## Latest Verification Evidence

| Date | Command | Result |
|---|---|---|
| 2026-04-29 | `python3 -m pytest --tb=short -q` | 413 passed, 2 skipped, 417 warnings |
| 2026-04-30 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -W error::DeprecationWarning -m pytest tests/test_scope_manager.py tests/test_knowledge_graph_session.py tests/test_pipeline.py tests/test_pipeline_integration.py --tb=short -q` | 128 passed |
| 2026-04-30 | `python3 -m pytest --tb=short -q` | 441 passed, 0 warnings |
| 2026-05-02 | `pytest -q` | 450 passed |
| 2026-05-02 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-02 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-02 | `python -m pytest tests/test_llm_wiki.py tests/test_cli.py --tb=short -q` | 45 passed |
| 2026-05-02 | `pytest -q` | 452 passed |
| 2026-05-02 | `python -m mnemosyne wiki rebuild/status/lint --format json` | CLI smoke passed |
| 2026-05-03 | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py --tb=short -q` | 39 passed |
| 2026-05-03 | `pytest -q` | 456 passed |
| 2026-05-03 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-03 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-03 | `python -m mnemosyne wiki rebuild/status/lint --format json --lock-timeout 1` | CLI smoke passed |
| 2026-05-03 | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` | 79 passed |
| 2026-05-03 | `pytest -q` | 459 passed |
| 2026-05-03 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-03 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-03 | `python -m mnemosyne wiki rebuild/status/lint --format json` | CLI smoke passed; unresolved contradiction warning and strict-lint failure verified |
| 2026-05-03 | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` | 81 passed |
| 2026-05-03 | `pytest -q` | 461 passed |
| 2026-05-03 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-03 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-03 | `python -m mnemosyne wiki rebuild/contradictions/resolve --format json` | CLI smoke passed; dry-run and write resolve behavior verified |
| 2026-05-03 | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` | 83 passed |
| 2026-05-03 | `pytest -q` | 463 passed |
| 2026-05-03 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-03 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-03 | `python -m mnemosyne wiki rebuild/prune --format json` | CLI smoke passed; dry-run plan and tombstone writes verified |

| 2026-05-03 | `python -m pytest tests/test_llm_wiki.py tests/test_ingest_cli.py tests/test_cli.py --tb=short -q` | 85 passed |
| 2026-05-03 | `pytest -q` | 465 passed |
| 2026-05-03 | `ruff check mnemosyne tests` | All checks passed |
| 2026-05-03 | `mypy mnemosyne` | Success: no issues found in 37 source files |
| 2026-05-03 | `python -m mnemosyne wiki semantic-contradictions --write --format json` | CLI smoke passed; local-offline semantic review candidates persisted without graph mutation |

| 2026-05-03 | `git diff --check && git diff --cached --check` | Moon Cell candidate SPEC docs refresh hygiene passed |

## Known Non-Blocking Warnings

| Warning | Source | Recommended Follow-Up |
|---|---|---|
| Async I/O deferred | Graph and pipeline I/O paths | Future SPEC only after API design decision |
