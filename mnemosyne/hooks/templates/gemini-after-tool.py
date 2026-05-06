"""Gemini CLI AfterTool hook — auto-sync mnemosyne after file writes.

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
