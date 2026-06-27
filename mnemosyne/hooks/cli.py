"""Hook management CLI — install, remove, and status for mnemosyne hooks.

Supports: git, claude, codex, gemini, copilot
"""
from __future__ import annotations

import importlib.resources
import json
import os
import stat
import sys
from pathlib import Path
from typing import Iterable, Optional, Union

ALL_TARGETS = ["git", "claude", "codex", "gemini", "copilot"]
DEFAULT_TARGETS = ["git", "claude"]

# Markers to identify mnemosyne-managed hooks in config files
_MNEMOSYNE_MARKER = "# mnemosyne-hook: managed"


def install(target: Optional[Union[str, Iterable[str]]], force: bool = False) -> None:
    """Install hooks for the specified target(s) (or all default targets)."""
    for t in _resolve_targets(target):
        _install_one(t, force)


def remove(target: Optional[Union[str, Iterable[str]]], remove_all: bool = False) -> None:
    """Remove hooks for the specified target(s)."""
    targets = ALL_TARGETS if remove_all else _resolve_targets(target)
    for t in targets:
        _remove_one(t)


def status() -> None:
    """Print installed hook status for all targets."""
    found_any = False
    for t in ALL_TARGETS:
        info = _status_one(t)
        icon = "installed" if info["installed"] else "not installed"
        path = info.get("path", "")
        print(f"  {t:10s} {icon:15s} {path}")
        found_any = True
    if not found_any:
        print("  No hook platforms detected.")


def _resolve_targets(target: Optional[Union[str, Iterable[str]]]) -> list[str]:
    if target is None:
        return DEFAULT_TARGETS
    if isinstance(target, str):
        target = [target]
    resolved: list[str] = []
    for t in target:
        if t == "all":
            return ALL_TARGETS
        if t not in ALL_TARGETS:
            print(f"Unknown target: {t}. Choose from: {', '.join(ALL_TARGETS)}")
            sys.exit(1)
        resolved.append(t)
    return resolved


# ── Installers ─────────────────────────────────────────────


def _install_one(target: str, force: bool) -> None:
    try:
        installer = _INSTALLERS[target]
    except KeyError:
        print(f"No installer for target: {target}")
        return
    installer(force)


def _install_git(force: bool) -> None:
    hook_path = _git_hook_path("post-commit")
    content = _read_template("git-post-commit.sh")

    if hook_path.exists() and not force:
        existing = hook_path.read_text(encoding="utf-8")
        if "mnemosyne" in existing:
            print(f"  git: already installed ({hook_path})")
            return
        print(f"  git: hook exists but is not mnemosyne ({hook_path}). Use --force to overwrite.")
        return

    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(content, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)
    print(f"  git: installed ({hook_path})")


def _install_claude(force: bool) -> None:
    settings_path = _claude_settings_path()
    script_path = _template_script_path("claude-post-tool.py")

    hook_entry = {
        "matcher": "Write|Edit",
        "hooks": [
            {
                "type": "command",
                "command": f"python3 {script_path}",
            }
        ],
    }

    _install_settings_hook(
        settings_path=settings_path,
        event="PostToolUse",
        hook_entry=hook_entry,
        identifier="mnemosyne-post-tool",
        force=force,
        platform="claude",
    )


def _install_codex(force: bool) -> None:
    hooks_path = _codex_hooks_path()
    script_path = _template_script_path("codex-post-tool.py")

    hook_config = {
        "event": "PostToolUse",
        "matcher": {"tool_name": "write|edit|create"},
        "command": f"python3 {script_path}",
    }

    _install_json_hooks_file(
        hooks_path=hooks_path,
        hook_entry=hook_config,
        identifier="mnemosyne-post-tool",
        force=force,
        platform="codex",
    )


def _install_gemini(force: bool) -> None:
    settings_path = _gemini_settings_path()
    script_path = _template_script_path("gemini-after-tool.py")

    hook_entry = {
        "matcher": "Write|Edit|write_file|edit_file",
        "hooks": [
            {
                "type": "command",
                "command": f"python3 {script_path}",
            }
        ],
    }

    _install_settings_hook(
        settings_path=settings_path,
        event="AfterTool",
        hook_entry=hook_entry,
        identifier="mnemosyne-after-tool",
        force=force,
        platform="gemini",
    )


def _install_copilot(force: bool) -> None:
    hooks_dir = _copilot_hooks_dir()
    script_path = _template_script_path("copilot-post-tool.py")

    hook_config = {
        "version": 1,
        "hooks": [
            {
                "event": "postToolUse",
                "match": {"toolName": "Write|Edit|write|edit"},
                "type": "command",
                "command": {"bash": f"python3 {script_path}"},
                "timeoutSec": 30,
            }
        ],
    }

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "mnemosyne.json"

    if hook_file.exists() and not force:
        print(f"  copilot: already installed ({hook_file})")
        return

    hook_file.write_text(json.dumps(hook_config, indent=2) + "\n", encoding="utf-8")
    print(f"  copilot: installed ({hook_file})")


_INSTALLERS = {
    "git": _install_git,
    "claude": _install_claude,
    "codex": _install_codex,
    "gemini": _install_gemini,
    "copilot": _install_copilot,
}


# ── Removers ───────────────────────────────────────────────


def _remove_one(target: str) -> None:
    try:
        remover = _REMOVERS[target]
    except KeyError:
        print(f"No remover for target: {target}")
        return
    remover()


def _remove_git() -> None:
    hook_path = _git_hook_path("post-commit")
    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        if "mnemosyne" in content:
            hook_path.unlink()
            print(f"  git: removed ({hook_path})")
            return
    print("  git: no mnemosyne hook found")


def _remove_claude() -> None:
    settings_path = _claude_settings_path()
    _remove_settings_hook(settings_path, "PostToolUse", "mnemosyne", "claude")


def _remove_codex() -> None:
    hooks_path = _codex_hooks_path()
    _remove_json_hooks_entry(hooks_path, "mnemosyne-post-tool", "codex")


def _remove_gemini() -> None:
    settings_path = _gemini_settings_path()
    _remove_settings_hook(settings_path, "AfterTool", "mnemosyne", "gemini")


def _remove_copilot() -> None:
    hooks_dir = _copilot_hooks_dir()
    hook_file = hooks_dir / "mnemosyne.json"
    if hook_file.exists():
        hook_file.unlink()
        print(f"  copilot: removed ({hook_file})")
    else:
        print("  copilot: no mnemosyne hook found")


_REMOVERS = {
    "git": _remove_git,
    "claude": _remove_claude,
    "codex": _remove_codex,
    "gemini": _remove_gemini,
    "copilot": _remove_copilot,
}


# ── Status ─────────────────────────────────────────────────


def _status_one(target: str) -> dict:
    checker = _STATUS_CHECKERS.get(target)
    if checker:
        return checker()
    return {"installed": False}


def _status_git() -> dict:
    hook_path = _git_hook_path("post-commit")
    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        if "mnemosyne" in content:
            return {"installed": True, "path": str(hook_path)}
    return {"installed": False, "path": str(hook_path)}


def _status_claude() -> dict:
    settings_path = _claude_settings_path()
    return _status_settings_hook(settings_path, "PostToolUse", "mnemosyne", "claude")


def _status_codex() -> dict:
    hooks_path = _codex_hooks_path()
    if hooks_path.exists():
        return {"installed": True, "path": str(hooks_path)}
    return {"installed": False, "path": str(hooks_path)}


def _status_gemini() -> dict:
    settings_path = _gemini_settings_path()
    return _status_settings_hook(settings_path, "AfterTool", "mnemosyne", "gemini")


def _status_copilot() -> dict:
    hooks_dir = _copilot_hooks_dir()
    hook_file = hooks_dir / "mnemosyne.json"
    if hook_file.exists():
        return {"installed": True, "path": str(hook_file)}
    return {"installed": False, "path": str(hook_file)}


_STATUS_CHECKERS = {
    "git": _status_git,
    "claude": _status_claude,
    "codex": _status_codex,
    "gemini": _status_gemini,
    "copilot": _status_copilot,
}


# ── Path Resolvers ─────────────────────────────────────────


def _git_hook_path(name: str) -> Path:
    return Path(os.environ.get("GIT_DIR", ".git")) / "hooks" / name


def _claude_settings_path() -> Path:
    return Path(".claude") / "settings.json"


def _codex_hooks_path() -> Path:
    return Path(".codex") / "hooks.json"


def _gemini_settings_path() -> Path:
    return Path(".gemini") / "settings.json"


def _copilot_hooks_dir() -> Path:
    return Path(".github") / "hooks"


# ── Template Helpers ───────────────────────────────────────


def _read_template(name: str) -> str:
    try:
        templates = importlib.resources.files("mnemosyne.hooks.templates")
        return (templates / name).read_text(encoding="utf-8")
    except (FileNotFoundError, AttributeError):
        fallback = Path(__file__).parent / "templates" / name
        return fallback.read_text(encoding="utf-8")


def _template_script_path(name: str) -> str:
    try:
        import mnemosyne.hooks.templates as _t

        return str(Path(_t.__file__).parent / name)
    except (ImportError, AttributeError):
        return str(Path(__file__).parent / "templates" / name)


# ── Settings File Helpers ──────────────────────────────────


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _install_settings_hook(
    settings_path: Path,
    event: str,
    hook_entry: dict,
    identifier: str,
    force: bool,
    platform: str,
) -> None:
    data = _load_json(settings_path)
    hooks = data.setdefault("hooks", {})
    event_hooks = hooks.setdefault(event, [])

    for existing in event_hooks:
        if _is_mnemosyne_hook(existing, identifier):
            if not force:
                print(f"  {platform}: already installed ({settings_path})")
                return
            event_hooks.remove(existing)
            break

    hook_entry["_mnemosyne"] = identifier
    event_hooks.append(hook_entry)

    _save_json(settings_path, data)
    print(f"  {platform}: installed ({settings_path})")


def _remove_settings_hook(
    settings_path: Path, event: str, identifier: str, platform: str
) -> None:
    if not settings_path.exists():
        print(f"  {platform}: no settings file found")
        return

    data = _load_json(settings_path)
    hooks = data.get("hooks", {})
    event_hooks = hooks.get(event, [])

    original_len = len(event_hooks)
    event_hooks[:] = [h for h in event_hooks if not _is_mnemosyne_hook(h, identifier)]

    if len(event_hooks) < original_len:
        if not event_hooks:
            hooks.pop(event, None)
        if not hooks:
            data.pop("hooks", None)
        _save_json(settings_path, data)
        print(f"  {platform}: removed ({settings_path})")
    else:
        print(f"  {platform}: no mnemosyne hook found")


def _status_settings_hook(
    settings_path: Path, event: str, identifier: str, platform: str
) -> dict:
    if not settings_path.exists():
        return {"installed": False, "path": str(settings_path)}

    data = _load_json(settings_path)
    hooks = data.get("hooks", {})
    event_hooks = hooks.get(event, [])

    for h in event_hooks:
        if _is_mnemosyne_hook(h, identifier):
            return {"installed": True, "path": str(settings_path)}

    return {"installed": False, "path": str(settings_path)}


def _install_json_hooks_file(
    hooks_path: Path,
    hook_entry: dict,
    identifier: str,
    force: bool,
    platform: str,
) -> None:
    data = _load_json(hooks_path)
    hooks_list = data.setdefault("hooks", [])

    for existing in hooks_list:
        if existing.get("_mnemosyne") == identifier:
            if not force:
                print(f"  {platform}: already installed ({hooks_path})")
                return
            hooks_list.remove(existing)
            break

    hook_entry["_mnemosyne"] = identifier
    hooks_list.append(hook_entry)

    _save_json(hooks_path, data)
    print(f"  {platform}: installed ({hooks_path})")


def _remove_json_hooks_entry(
    hooks_path: Path, identifier: str, platform: str
) -> None:
    if not hooks_path.exists():
        print(f"  {platform}: no hooks file found")
        return

    data = _load_json(hooks_path)
    hooks_list = data.get("hooks", [])

    original_len = len(hooks_list)
    hooks_list[:] = [h for h in hooks_list if h.get("_mnemosyne") != identifier]

    if len(hooks_list) < original_len:
        if not hooks_list:
            data.pop("hooks", None)
        _save_json(hooks_path, data)
        print(f"  {platform}: removed ({hooks_path})")
    else:
        print(f"  {platform}: no mnemosyne hook found")


def _is_mnemosyne_hook(entry: dict, identifier: str) -> bool:
    return entry.get("_mnemosyne", "").startswith(identifier)
