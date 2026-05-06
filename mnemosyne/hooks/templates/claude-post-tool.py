"""Claude Code PostToolUse hook — auto-sync mnemosyne after file writes.

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
