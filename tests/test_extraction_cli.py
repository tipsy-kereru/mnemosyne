"""Tests for extraction CLI (SPEC-PROD-002, REQ-001).

Covers mnemosyne/extraction/cli.py: path validation, domain routing,
format output, and the __main__ entry point.
"""

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from mnemosyne.extraction.cli import main


@dataclass
class FakeEntity:
    type: str
    name: str
    language: str
    file_path: str
    line_start: int
    line_end: int
    properties: dict
    scope_id: str | None = None
    source_channel: str | None = None


@dataclass
class FakeParseResult:
    entities: list | None = None
    imports: list | None = None
    calls: list | None = None
    file_path: str = ""
    language: str = ""
    content_hash: str = ""
    extraction_method: str = ""

    def __post_init__(self):
        if self.entities is None:
            self.entities = []
        if self.imports is None:
            self.imports = []
        if self.calls is None:
            self.calls = []


@pytest.fixture
def sample_py_file(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text(textwrap.dedent("""\
        def hello():
            pass
    """))
    return p


@pytest.fixture
def fake_entity():
    return FakeEntity(
        type="function",
        name="hello",
        language="python",
        file_path="sample.py",
        line_start=1,
        line_end=2,
        properties={},
    )


class TestExtractionCLIPathValidation:
    def test_nonexistent_path_exits(self):
        with pytest.raises(SystemExit):
            main(["/nonexistent/path.py"])

    def test_nonexistent_path_message(self, capsys):
        with pytest.raises(SystemExit):
            main(["/nonexistent/path.py"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestExtractionCLICodingDomain:
    def test_single_file_json_output(self, sample_py_file, fake_entity, capsys):
        fake_result = FakeParseResult(entities=[fake_entity])

        with patch(
            "mnemosyne.extraction.deterministic.code_parser.TreeSitterExtractor"
        ) as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract_file_full.return_value = fake_result

            main([str(sample_py_file), "--domain", "coding", "--format", "json"])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert isinstance(output, list)
        assert output[0]["name"] == "hello"

    def test_single_file_wiki_output(self, sample_py_file, fake_entity, capsys):
        fake_result = FakeParseResult(entities=[fake_entity])

        with patch(
            "mnemosyne.extraction.deterministic.code_parser.TreeSitterExtractor"
        ) as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract_file_full.return_value = fake_result
            instance.to_wiki_format.return_value = "# Code Entities\n\n## Functions\n"

            main([str(sample_py_file), "--domain", "coding", "--format", "wiki"])

        captured = capsys.readouterr()
        assert "Code Entities" in captured.out

    def test_directory_extraction(self, tmp_path, fake_entity, capsys):
        (tmp_path / "a.py").write_text("def a(): pass")

        with patch(
            "mnemosyne.extraction.deterministic.code_parser.TreeSitterExtractor"
        ) as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract_directory.return_value = [fake_entity]

            main([str(tmp_path), "--domain", "coding", "--format", "json"])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert isinstance(output, list)

    def test_scope_id_and_source_channel(
        self, sample_py_file, fake_entity, capsys
    ):
        fake_result = FakeParseResult(entities=[fake_entity])

        with patch(
            "mnemosyne.extraction.deterministic.code_parser.TreeSitterExtractor"
        ) as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract_file_full.return_value = fake_result

            main([
                str(sample_py_file),
                "--domain", "coding",
                "--scope-id", "session-1",
                "--source-channel", "vscode",
            ])

        instance.extract_file_full.assert_called_once_with(
            sample_py_file,
            scope_id="session-1",
            source_channel="vscode",
        )


class TestExtractionCLIUnsupportedDomain:
    def test_daily_domain_exits(self, sample_py_file, capsys):
        with pytest.raises(SystemExit):
            main([str(sample_py_file), "--domain", "daily"])

    def test_legal_domain_exits(self, sample_py_file, capsys):
        with pytest.raises(SystemExit):
            main([str(sample_py_file), "--domain", "legal"])

    def test_unsupported_domain_message(self, sample_py_file, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([str(sample_py_file), "--domain", "daily"])
        assert exc_info.value.code == 1


class TestExtractionCLIEntryPoint:
    def test_module_entry_point_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne.extraction.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "domain" in result.stdout.lower()

    def test_main_module_runs(self, tmp_path):
        """python -m mnemosyne.extraction.cli with a real file."""
        p = tmp_path / "test.py"
        p.write_text("def foo(): pass\n")

        result = subprocess.run(
            [sys.executable, "-m", "mnemosyne.extraction.cli", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
