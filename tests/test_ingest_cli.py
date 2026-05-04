"""
Tests for the mnemosyne ingest CLI and supporting ingestion modules.

Covers:
  - LLM provider detection and extraction (LLMBridge)
  - Text-level extraction with chunking (LLMExtractor)
  - URL fetching and slug generation (URLFetcher)
  - End-to-end ingestion (Ingester)
  - Incremental update bookkeeping (Updater)
  - mnemosyne CLI ``add`` and ``update`` subcommands

All external I/O (LLM calls, HTTP, filesystem writes that escape tmp_path)
is mocked. These tests do not require API keys or network access.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — the ingest module ships dataclasses we want to introspect.
# Importing inside fixtures keeps the test module importable even before
# the parallel agent finishes writing the modules (CI selects tests by name).
# ---------------------------------------------------------------------------


def _import_or_skip(module_path: str):
    """Import ``module_path`` or skip the calling test if unavailable."""
    try:
        import importlib

        return importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - protective
        pytest.skip(f"{module_path} not available: {exc}")


# ---------------------------------------------------------------------------
# LLMBridge — provider detection
# ---------------------------------------------------------------------------


class TestLLMBridgeProviderDetection:
    """Verify that LLMBridge picks the right provider from environment vars."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "MNEMOSYNE_LLM",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_detects_anthropic_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "anthropic"

    def test_detects_openai_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "openai"

    def test_detects_google_from_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "google"

    def test_cli_fallback_when_no_keys(self):
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "cli"

    def test_mnemosyne_llm_env_overrides(self, monkeypatch):
        # Even if Anthropic key is present, the explicit override should win.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("MNEMOSYNE_LLM", "openai")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "openai"


# ---------------------------------------------------------------------------
# LLMBridge — extract behavior
# ---------------------------------------------------------------------------


class TestLLMBridgeExtract:
    """Verify error handling and output shape of LLMBridge.extract()."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "MNEMOSYNE_LLM",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_returns_empty_on_json_parse_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()

        # Force the anthropic call to return a non-JSON string.
        with patch.object(bridge, "_call_anthropic", return_value="not valid json"):
            result = bridge.extract("hello world", schema_hint="")

        assert isinstance(result, dict)
        assert result.get("nodes") == []
        assert result.get("edges") == []
        assert "error" in result

    def test_cli_fallback_when_claude_not_found(self, monkeypatch):
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()
        assert bridge.provider == "cli"

        # shutil.which should report claude is missing → graceful error dict.
        with patch("shutil.which", return_value=None):
            result = bridge.extract("hello world", schema_hint="")

        assert isinstance(result, dict)
        assert result.get("nodes") == []
        assert result.get("edges") == []
        assert "error" in result

    def test_anthropic_extract_parses_valid_json(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        bridge_module = _import_or_skip("mnemosyne.ingest.llm_bridge")
        bridge = bridge_module.LLMBridge()

        valid_payload = json.dumps({
            "nodes": [
                {"id": "john", "type": "person", "label": "John"},
            ],
            "edges": [
                {"source": "john", "target": "google", "relation": "works_at"},
            ],
        })

        with patch.object(bridge, "_call_anthropic", return_value=valid_payload):
            result = bridge.extract("John works at Google", schema_hint="")

        assert isinstance(result, dict)
        assert len(result.get("nodes", [])) == 1
        assert result["nodes"][0]["label"] == "John"
        assert len(result.get("edges", [])) == 1


# ---------------------------------------------------------------------------
# LLMExtractor — chunking and merging
# ---------------------------------------------------------------------------


class TestLLMExtractor:
    """Verify text/file extraction and chunk merge behavior."""

    def test_extract_text_returns_parsed_result(self):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")

        fake_bridge = MagicMock()
        fake_bridge.extract.return_value = {
            "nodes": [{"id": "n1", "type": "person", "label": "John"}],
            "edges": [],
        }

        extractor = ext_module.LLMExtractor(bridge=fake_bridge)
        result = extractor.extract_text("John lives in Paris.")

        assert isinstance(result, ext_module.ParsedIngestResult)
        assert len(result.entities) == 1
        assert result.entities[0].label == "John"

    def test_extract_text_chunks_long_text(self):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")

        fake_bridge = MagicMock()
        fake_bridge.extract.return_value = {"nodes": [], "edges": []}

        extractor = ext_module.LLMExtractor(bridge=fake_bridge)
        long_text = "X" * 10_000  # well over the 3000 char chunk threshold

        extractor.extract_text(long_text)
        # Long text should produce multiple bridge.extract() calls.
        assert fake_bridge.extract.call_count >= 2

    def test_extract_file_reads_file(self, tmp_path):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")

        sample = tmp_path / "note.md"
        sample.write_text("Alice met Bob at the conference.", encoding="utf-8")

        fake_bridge = MagicMock()
        fake_bridge.extract.return_value = {
            "nodes": [{"id": "alice", "type": "person", "label": "Alice"}],
            "edges": [],
        }

        extractor = ext_module.LLMExtractor(bridge=fake_bridge)
        result = extractor.extract_file(sample)

        # File content should have been forwarded to the bridge.
        assert fake_bridge.extract.called
        sent_text = fake_bridge.extract.call_args[0][0]
        assert "Alice" in sent_text or "Bob" in sent_text
        assert isinstance(result, ext_module.ParsedIngestResult)

    def test_extract_merges_chunks(self):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")

        # Two chunks return overlapping entity ids → final result is deduped.
        fake_bridge = MagicMock()
        fake_bridge.extract.side_effect = [
            {
                "nodes": [
                    {"id": "shared", "type": "person", "label": "Alice"},
                    {"id": "only-a", "type": "person", "label": "Anna"},
                ],
                "edges": [],
            },
            {
                "nodes": [
                    {"id": "shared", "type": "person", "label": "Alice"},
                    {"id": "only-b", "type": "person", "label": "Bob"},
                ],
                "edges": [],
            },
        ]

        extractor = ext_module.LLMExtractor(bridge=fake_bridge)
        long_text = "Y" * 5_000  # forces exactly two chunks (3000 + 2000)
        result = extractor.extract_text(long_text)

        ids = {e.id for e in result.entities}
        assert "shared" in ids
        assert len(ids) == len(result.entities), "duplicate ids leaked into result"


# ---------------------------------------------------------------------------
# URLFetcher — basic dispatching and slug rules
# ---------------------------------------------------------------------------


class TestURLFetcher:
    """Verify URL routing and on-disk persistence behavior."""

    def test_arxiv_url_detection(self, tmp_path):
        from mnemosyne.ingest.url_fetcher import URLFetcher

        fetcher = URLFetcher()
        with patch.object(fetcher, "_fetch_arxiv", return_value="---\n---\n# arxiv\n") as mock_arxiv, \
             patch.object(fetcher, "_fetch_webpage") as mock_web:
            fetcher.fetch("https://arxiv.org/abs/2305.10601", raw_dir=tmp_path)

        mock_arxiv.assert_called_once()
        mock_web.assert_not_called()

    def test_generic_url_saves_to_raw_dir(self, tmp_path):
        from mnemosyne.ingest.url_fetcher import URLFetcher

        fetcher = URLFetcher()
        fake_response = MagicMock()
        fake_response.read.return_value = b"<html><title>Hi</title><body>Body</body></html>"
        fake_response.headers = {"Content-Type": "text/html"}
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_response):
            out_path = fetcher.fetch("https://example.com/article", raw_dir=tmp_path)

        assert out_path.exists()
        assert out_path.parent == tmp_path
        content = out_path.read_text(encoding="utf-8")
        assert "source_url:" in content

    def test_slug_from_url(self):
        from mnemosyne.ingest.url_fetcher import URLFetcher

        slug = URLFetcher._slugify("https://example.com/Article?id=42&x=Y%20Z")
        assert slug, "slug should not be empty"
        assert len(slug) <= 60
        # Only lowercase alphanumerics and underscores.
        assert all(c.isalnum() or c == "_" for c in slug)


# ---------------------------------------------------------------------------
# Ingester — orchestration
# ---------------------------------------------------------------------------


class TestIngester:
    """Verify Ingester dispatches to extractor + KG correctly."""

    def _make_parsed_result(self, ingest_module):
        entity = ingest_module.IngestEntity(
            id="john", label="John", type="person", source_file=""
        )
        entity2 = ingest_module.IngestEntity(
            id="google", label="Google", type="organization", source_file=""
        )
        relation = ingest_module.IngestRelation(
            source="john", target="google", relation="works_at"
        )
        return ingest_module.ParsedIngestResult(
            entities=[entity, entity2], relations=[relation]
        )

    def test_add_text_returns_ingest_result(self):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")
        ing_module = _import_or_skip("mnemosyne.ingest.ingester")

        parsed = self._make_parsed_result(ext_module)

        with patch("mnemosyne.ingest.ingester.LLMExtractor") as mock_extractor_cls, \
             patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph") as mock_kg_cls:
            mock_extractor = MagicMock()
            mock_extractor.extract_text.return_value = parsed
            mock_extractor_cls.return_value = mock_extractor

            mock_kg = MagicMock()
            mock_kg.get_entity.return_value = None
            mock_kg_cls.return_value = mock_kg

            ingester = ing_module.Ingester()
            result = ingester.add(target="", text="John works at Google", domain="daily")

        assert isinstance(result, ing_module.IngestResult)
        assert result.entities_added >= 1
        assert result.relations_added == 1

    def test_add_url_calls_fetcher(self, tmp_path):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")
        ing_module = _import_or_skip("mnemosyne.ingest.ingester")

        parsed = self._make_parsed_result(ext_module)
        raw_path = tmp_path / "fetched.md"
        raw_path.write_text("---\n---\n# fetched\n", encoding="utf-8")

        with patch("mnemosyne.ingest.ingester.URLFetcher") as mock_fetcher_cls, \
             patch("mnemosyne.ingest.ingester.LLMExtractor") as mock_extractor_cls, \
             patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph") as mock_kg_cls:
            mock_fetcher = MagicMock()
            mock_fetcher.fetch.return_value = raw_path
            mock_fetcher_cls.return_value = mock_fetcher

            mock_extractor = MagicMock()
            mock_extractor.extract_file.return_value = parsed
            mock_extractor.extract_text.return_value = parsed
            mock_extractor_cls.return_value = mock_extractor

            mock_kg = MagicMock()
            mock_kg.get_entity.return_value = None
            # fetchone() must return None so _is_unchanged() treats file as new
            mock_kg.conn.execute.return_value.fetchone.return_value = None
            mock_kg_cls.return_value = mock_kg

            ingester = ing_module.Ingester()
            result = ingester.add(target="https://example.com/x", domain="daily")

        mock_fetcher.fetch.assert_called_once()
        assert isinstance(result, ing_module.IngestResult)
        assert result.entities_added >= 1

    def test_dry_run_does_not_write(self):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")
        ing_module = _import_or_skip("mnemosyne.ingest.ingester")

        parsed = self._make_parsed_result(ext_module)

        with patch("mnemosyne.ingest.ingester.LLMExtractor") as mock_extractor_cls, \
             patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph") as mock_kg_cls:
            mock_extractor = MagicMock()
            mock_extractor.extract_text.return_value = parsed
            mock_extractor_cls.return_value = mock_extractor

            mock_kg = MagicMock()
            mock_kg.get_entity.return_value = None
            mock_kg_cls.return_value = mock_kg

            ingester = ing_module.Ingester(dry_run=True)
            result = ingester.add(target="", text="hi", domain="daily")

        # In dry-run mode the KG should not record entities/relations.
        mock_kg.add_entity.assert_not_called()
        mock_kg.add_relation.assert_not_called()
        assert isinstance(result, ing_module.IngestResult)

    def test_add_text_updates_llm_wiki_when_configured(self, tmp_path):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")
        ing_module = _import_or_skip("mnemosyne.ingest.ingester")

        parsed = self._make_parsed_result(ext_module)

        with patch("mnemosyne.ingest.ingester.LLMExtractor") as mock_extractor_cls, \
             patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph") as mock_kg_cls:
            mock_extractor = MagicMock()
            mock_extractor.extract_text.return_value = parsed
            mock_extractor_cls.return_value = mock_extractor

            mock_kg = MagicMock()
            mock_kg.get_entity.return_value = None
            mock_kg_cls.return_value = mock_kg

            wiki_root = tmp_path / "wiki"
            ingester = ing_module.Ingester(wiki_root=wiki_root)
            result = ingester.add(
                target="",
                text="John works at Google",
                domain="daily",
                scope_id="demo",
            )

        assert result.wiki_paths
        assert (wiki_root / "index.md").exists()
        assert (wiki_root / "log.md").exists()
        assert (wiki_root / "entities" / "person" / "john.md").exists()
        assert "John" in (wiki_root / "index.md").read_text(encoding="utf-8")

    def test_add_directory_aggregates_files(self, tmp_path):
        ext_module = _import_or_skip("mnemosyne.ingest.llm_extractor")
        ing_module = _import_or_skip("mnemosyne.ingest.ingester")

        # Two markdown files in the directory.
        (tmp_path / "a.md").write_text("Alice met Bob.", encoding="utf-8")
        (tmp_path / "b.md").write_text("Carol called Dave.", encoding="utf-8")

        parsed = self._make_parsed_result(ext_module)

        with patch("mnemosyne.ingest.ingester.LLMExtractor") as mock_extractor_cls, \
             patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph") as mock_kg_cls:
            mock_extractor = MagicMock()
            mock_extractor.extract_file.return_value = parsed
            mock_extractor.extract_text.return_value = parsed
            mock_extractor_cls.return_value = mock_extractor

            mock_kg = MagicMock()
            mock_kg.get_entity.return_value = None
            mock_kg.conn.execute.return_value.fetchone.return_value = None
            mock_kg_cls.return_value = mock_kg

            ingester = ing_module.Ingester()
            # add_directory returns a list; add() for a dir merges into one result
            results = ingester.add_directory(tmp_path, domain="daily")

        assert isinstance(results, list)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Updater — incremental change detection
# ---------------------------------------------------------------------------


class TestUpdater:
    """Verify content-hash-based update detection."""

    def _make_mock_kg(self, db_path):
        """Return a mock KG that uses a real SQLite connection for cache ops."""
        import sqlite3

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        mock_kg = MagicMock()
        mock_kg.conn = conn
        mock_kg.get_entity.return_value = None
        return mock_kg, conn

    def test_update_skips_unchanged_files(self, tmp_path):
        upd_module = _import_or_skip("mnemosyne.ingest.update")

        sample = tmp_path / "n.md"
        sample.write_text("hello world", encoding="utf-8")

        mock_kg, conn = self._make_mock_kg(tmp_path / "test.db")
        try:
            with patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph", return_value=mock_kg), \
                 patch("mnemosyne.ingest.llm_extractor.LLMBridge") as mock_bridge_cls:
                mock_bridge_cls.return_value.extract.return_value = {"nodes": [], "edges": []}

                updater = upd_module.Updater(db_path=tmp_path / "test.db", raw_root=tmp_path)
                first = updater.update(path=tmp_path)
                second = updater.update(path=tmp_path)
        finally:
            conn.close()

        assert first.new_files >= 1, "first run should detect new file"
        assert second.unchanged >= 1, "second run should find file unchanged"
        assert second.changed == 0

    def test_update_detects_changed_files(self, tmp_path):
        upd_module = _import_or_skip("mnemosyne.ingest.update")

        sample = tmp_path / "n.md"
        sample.write_text("hello world", encoding="utf-8")

        mock_kg, conn = self._make_mock_kg(tmp_path / "test.db")
        try:
            with patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph", return_value=mock_kg), \
                 patch("mnemosyne.ingest.llm_extractor.LLMBridge") as mock_bridge_cls:
                mock_bridge_cls.return_value.extract.return_value = {"nodes": [], "edges": []}

                updater = upd_module.Updater(db_path=tmp_path / "test.db", raw_root=tmp_path)
                updater.update(path=tmp_path)

                sample.write_text("hello world v2", encoding="utf-8")
                second = updater.update(path=tmp_path)
        finally:
            conn.close()

        assert second.changed >= 1

    def test_stats_only_does_not_write(self, tmp_path):
        upd_module = _import_or_skip("mnemosyne.ingest.update")

        sample = tmp_path / "n.md"
        sample.write_text("hello world", encoding="utf-8")

        mock_kg, conn = self._make_mock_kg(tmp_path / "test.db")
        try:
            with patch("mnemosyne.graph.knowledge_graph.KnowledgeGraph", return_value=mock_kg):
                updater = upd_module.Updater(db_path=tmp_path / "test.db", raw_root=tmp_path)
                updater.stats_only(path=tmp_path)
        finally:
            conn.close()

        # stats_only never calls KG write operations
        mock_kg.add_entity.assert_not_called()
        mock_kg.add_relation.assert_not_called()


# ---------------------------------------------------------------------------
# CLI — add / update subcommand parsing and dispatch
# ---------------------------------------------------------------------------


class TestCLIAddCommand:
    """Verify the ``mnemosyne add`` and ``mnemosyne update`` subcommands."""

    def test_mnemosyne_add_text_flag(self):
        from mnemosyne.cli import main

        with patch("mnemosyne.cli._run_add") as mock_run:
            main(["add", "--text", "hello world", "--domain", "daily"])

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.text == "hello world"
        assert args.domain == "daily"
        assert args.target is None

    def test_mnemosyne_add_requires_target_or_text(self, capsys):
        from mnemosyne.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["add"])

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "target" in captured.err.lower() or "--text" in captured.err.lower()

    def test_mnemosyne_update_default_path(self):
        from mnemosyne.cli import main

        with patch("mnemosyne.cli._run_update") as mock_run:
            main(["update"])

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args.path is None
        assert args.domain == "auto"


def test_ingester_merges_existing_entities_and_records_history(tmp_path):
    from mnemosyne.graph.knowledge_graph import KnowledgeGraph
    from mnemosyne.ingest.ingester import Ingester

    class FakeBridge:
        def __init__(self):
            self.calls = 0

        def extract(self, text, schema_hint="", domain="daily"):
            self.calls += 1
            role = "engineer" if self.calls == 1 else "architect"
            return {
                "nodes": [
                    {
                        "id": "alice",
                        "type": "person",
                        "label": "Alice",
                        "properties": {"role": role},
                    }
                ],
                "edges": [],
            }

    db_path = tmp_path / "kg.db"
    ingester = Ingester(db_path=db_path, llm_bridge=FakeBridge(), wiki_root=None)
    first = ingester.add("", text="Alice is an engineer", domain="daily")
    second = ingester.add("", text="Alice is an architect", domain="daily")
    ingester.close()

    assert first.entities_added == 1
    assert second.entities_added == 0

    kg = KnowledgeGraph(str(db_path))
    entity = kg.get_entity("alice")
    assert entity is not None
    assert entity.version == 2
    assert entity.properties["role"] == "engineer"
    assert "conflicts" in entity.properties
    conflict = entity.properties["conflicts"]["role"][0]
    assert conflict["incoming"] == "architect"
    assert conflict["resolution"] == "unresolved"
    assert conflict["source_id"]
    assert conflict["detected_at"] == conflict["seen_at"]
    assert len(kg.get_entity_history("alice")) == 2
    kg.close()
