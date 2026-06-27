"""Bundled hook template sources.

The hook templates live as separate files under ``mnemosyne/hooks/templates/``
for pip installs (the host agent executes them by path). In the PyOxidizer
frozen binary those non-Python data files are not reliably readable via
``importlib.resources`` (``ValueError`` on ``read_text``), so the same content
is duplicated here as string constants and ``_read_template`` consults this
dict first.

Keep these in sync with the files under ``templates/``. The test suite
(``tests/test_hooks_templates_sync.py``) asserts equality.
"""

from __future__ import annotations

CLAUDE_POST_TOOL_PY = r'''"""Claude Code PostToolUse hook — auto-sync mnemosyne after file writes.

Installed by: mnemosyne hook install claude
Input: JSON on stdin with tool_name, tool_input, tool_output
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    subprocess.run(
        ["mnemosyne", "add", file_path, "--quiet"],
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    main()
'''

CODEX_POST_TOOL_PY = r'''"""OpenAI Codex PostToolUse hook — auto-sync mnemosyne after file writes.

Installed by: mnemosyne hook install codex
Input: JSON on stdin with session_id, tool_name, tool_input, tool_output
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_name = data.get("tool_name", "")
    if tool_name not in ("write", "edit", "create"):
        return

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", tool_input.get("path", ""))
    if not file_path:
        return

    subprocess.run(
        ["mnemosyne", "add", file_path, "--quiet"],
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    main()
'''

COPILOT_POST_TOOL_PY = r'''"""GitHub Copilot postToolUse hook — auto-sync mnemosyne after file writes.

Installed by: mnemosyne hook install copilot
Input: JSON on stdin with toolName, toolInput, toolOutput
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_name = data.get("toolName", "")
    if tool_name not in ("Write", "Edit", "write", "edit"):
        return

    tool_input = data.get("toolInput", {})
    file_path = tool_input.get("file_path", tool_input.get("path", ""))
    if not file_path:
        return

    subprocess.run(
        ["mnemosyne", "add", file_path, "--quiet"],
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    main()
'''

GEMINI_AFTER_TOOL_PY = r'''"""Gemini CLI AfterTool hook — auto-sync mnemosyne after file writes.

Installed by: mnemosyne hook install gemini
Input: JSON on stdin with toolName, toolInput, toolOutput
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_name = data.get("toolName", "")
    if tool_name not in ("Write", "Edit", "write_file", "edit_file"):
        return

    tool_input = data.get("toolInput", {})
    file_path = tool_input.get("file_path", tool_input.get("path", ""))
    if not file_path:
        return

    subprocess.run(
        ["mnemosyne", "add", file_path, "--quiet"],
        capture_output=True,
        timeout=60,
    )


if __name__ == "__main__":
    main()
'''

GIT_POST_COMMIT_SH = r'''#!/bin/sh
# mnemosyne post-commit hook — auto-sync knowledge graph after commits
# Installed by: mnemosyne hook install git
# Managed by mnemosyne — do not edit manually

# Only run if mnemosyne is available
command -v mnemosyne >/dev/null 2>&1 || exit 0

# Run incremental update — mnemosyne uses hash-based change detection
# so this is fast when nothing has changed
mnemosyne update --quiet 2>/dev/null
'''

TEMPLATES: dict[str, str] = {
    "claude-post-tool.py": CLAUDE_POST_TOOL_PY,
    "codex-post-tool.py": CODEX_POST_TOOL_PY,
    "copilot-post-tool.py": COPILOT_POST_TOOL_PY,
    "gemini-after-tool.py": GEMINI_AFTER_TOOL_PY,
    "git-post-commit.sh": GIT_POST_COMMIT_SH,
}
