"""Tests for mnemosyne hook install/remove/status — SPEC-HOOKS-001."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from mnemosyne.hooks.cli import (
    ALL_TARGETS,
    install,
    remove,
    status,
)


@pytest.fixture
def tmp_project(tmp_path: Path):
    """Create a minimal project directory with .git/hooks."""
    git_hooks = tmp_path / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return tmp_path


class TestGitHook:
    def test_install_creates_post_commit(self, tmp_project: Path) -> None:
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=tmp_project / ".git" / "hooks" / "post-commit"):
            install("git")
        hook = tmp_project / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        assert hook.stat().st_mode & stat.S_IEXEC
        assert "mnemosyne" in hook.read_text()

    def test_install_idempotent(self, tmp_project: Path) -> None:
        hook = tmp_project / ".git" / "hooks" / "post-commit"
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=hook):
            install("git")
            install("git")
        assert "mnemosyne" in hook.read_text()

    def test_remove_deletes_hook(self, tmp_project: Path) -> None:
        hook = tmp_project / ".git" / "hooks" / "post-commit"
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=hook):
            install("git")
            remove("git")
        assert not hook.exists()

    def test_remove_no_hook_no_error(self, tmp_project: Path) -> None:
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=tmp_project / ".git" / "hooks" / "post-commit"):
            remove("git")  # should not raise


class TestClaudeHook:
    def test_install_adds_to_settings(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.json"
        with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=settings):
            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                install("claude")
        data = json.loads(settings.read_text())
        hooks = data["hooks"]["PostToolUse"]
        assert any(h.get("_mnemosyne", "").startswith("mnemosyne") for h in hooks)

    def test_remove_cleans_settings(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.json"
        with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=settings):
            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                install("claude")
                remove("claude")
        if settings.exists():
            data = json.loads(settings.read_text())
            assert "hooks" not in data


class TestCodexHook:
    def test_install_creates_hooks_json(self, tmp_path: Path) -> None:
        hooks_file = tmp_path / ".codex" / "hooks.json"
        with patch("mnemosyne.hooks.cli._codex_hooks_path", return_value=hooks_file):
            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                install("codex")
        data = json.loads(hooks_file.read_text())
        assert any(h.get("_mnemosyne") == "mnemosyne-post-tool" for h in data.get("hooks", []))


class TestGeminiHook:
    def test_install_adds_to_settings(self, tmp_path: Path) -> None:
        settings = tmp_path / ".gemini" / "settings.json"
        with patch("mnemosyne.hooks.cli._gemini_settings_path", return_value=settings):
            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                install("gemini")
        data = json.loads(settings.read_text())
        assert "AfterTool" in data.get("hooks", {})


class TestCopilotHook:
    def test_install_creates_json(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / ".github" / "hooks"
        with patch("mnemosyne.hooks.cli._copilot_hooks_dir", return_value=hooks_dir):
            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                install("copilot")
        hook_file = hooks_dir / "mnemosyne.json"
        assert hook_file.exists()
        data = json.loads(hook_file.read_text())
        assert data["version"] == 1


class TestStatusCommand:
    def test_status_runs_without_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=tmp_path / ".git" / "hooks" / "post-commit"):
            with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=tmp_path / ".claude" / "settings.json"):
                with patch("mnemosyne.hooks.cli._codex_hooks_path", return_value=tmp_path / ".codex" / "hooks.json"):
                    with patch("mnemosyne.hooks.cli._gemini_settings_path", return_value=tmp_path / ".gemini" / "settings.json"):
                        with patch("mnemosyne.hooks.cli._copilot_hooks_dir", return_value=tmp_path / ".github" / "hooks"):
                            status()
        out = capsys.readouterr().out
        for t in ALL_TARGETS:
            assert t in out


class TestDefaultTargets:
    def test_install_no_target_installs_git_and_claude(self, tmp_path: Path) -> None:
        git_hook = tmp_path / ".git" / "hooks" / "post-commit"
        claude_settings = tmp_path / ".claude" / "settings.json"

        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=git_hook):
            with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=claude_settings):
                with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                    install(None)

        assert git_hook.exists()
        assert claude_settings.exists()

    def test_install_all_targets(self, tmp_path: Path) -> None:
        paths = {
            "git": tmp_path / ".git" / "hooks" / "post-commit",
            "claude": tmp_path / ".claude" / "settings.json",
            "codex": tmp_path / ".codex" / "hooks.json",
            "gemini": tmp_path / ".gemini" / "settings.json",
            "copilot": tmp_path / ".github" / "hooks",
        }
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=paths["git"]):
            with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=paths["claude"]):
                with patch("mnemosyne.hooks.cli._codex_hooks_path", return_value=paths["codex"]):
                    with patch("mnemosyne.hooks.cli._gemini_settings_path", return_value=paths["gemini"]):
                        with patch("mnemosyne.hooks.cli._copilot_hooks_dir", return_value=paths["copilot"]):
                            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                                install("all")

        assert paths["git"].exists()
        assert paths["claude"].exists()
        assert paths["codex"].exists()
        assert paths["gemini"].exists()
        assert (paths["copilot"] / "mnemosyne.json").exists()

    def test_remove_all_targets(self, tmp_path: Path) -> None:
        git_hook = tmp_path / ".git" / "hooks" / "post-commit"
        claude_settings = tmp_path / ".claude" / "settings.json"
        codex_hooks = tmp_path / ".codex" / "hooks.json"
        gemini_settings = tmp_path / ".gemini" / "settings.json"
        copilot_dir = tmp_path / ".github" / "hooks"

        # Install first
        with patch("mnemosyne.hooks.cli._git_hook_path", return_value=git_hook):
            with patch("mnemosyne.hooks.cli._claude_settings_path", return_value=claude_settings):
                with patch("mnemosyne.hooks.cli._codex_hooks_path", return_value=codex_hooks):
                    with patch("mnemosyne.hooks.cli._gemini_settings_path", return_value=gemini_settings):
                        with patch("mnemosyne.hooks.cli._copilot_hooks_dir", return_value=copilot_dir):
                            with patch("mnemosyne.hooks.cli._template_script_path", return_value="/fake/script.py"):
                                install("all")
                                remove("git", remove_all=True)

        assert not git_hook.exists()
