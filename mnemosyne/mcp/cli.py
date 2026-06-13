"""``mnemosyne mcp`` subcommand (SPEC-MCP-001).

Provides two sub-actions:
  - ``serve``              : run the MCP stdio server (REQ-MCP-001).
  - ``install --client X`` : print a stdio config snippet for common MCP
    clients (REQ-MCP-010). No file writes outside the repo unless --apply.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict


def _server_command() -> list[str]:
    """Return the stdio command+args that launch this MCP server.

    Uses ``python -m mnemosyne.mcp`` so the snippet works in any venv without
    relying on a console_scripts wrapper (REQ-MCP-010).
    """
    import sys as _sys

    return [_sys.executable, "-m", "mnemosyne.mcp"]


def _install_snippets() -> Dict[str, Dict[str, object]]:
    """Return per-client stdio config snippets (REQ-MCP-010).

    Each snippet is the JSON object the user pastes into their client's MCP
    config under the server name ``mnemosyne``.
    """
    cmd = _server_command()
    return {
        "claude-desktop": {
            "file": "~/Library/Application Support/Claude/claude_desktop_config.json"
            if sys.platform == "darwin"
            else "~/.config/claude/claude_desktop_config.json",
            "config": {
                "mcpServers": {
                    "mnemosyne": {
                        "command": cmd[0],
                        "args": cmd[1:],
                    }
                }
            },
            "note": "Add the 'mnemosyne' entry to the mcpServers object.",
        },
        "hermes": {
            "config": {
                "mcp": {
                    "mnemosyne": {
                        "command": cmd[0],
                        "args": cmd[1:],
                        "transport": "stdio",
                    }
                }
            },
            "note": "Merge under the 'mcp' key of your Hermes config.",
        },
        "openclaw": {
            "config": {
                "mcpServers": {
                    "mnemosyne": {
                        "command": cmd[0],
                        "args": cmd[1:],
                        "transport": "stdio",
                    }
                }
            },
            "note": "Merge under 'mcpServers' in your OpenClaw config.",
        },
    }


def _run_serve(args: argparse.Namespace) -> int:
    """Run the MCP stdio server (REQ-MCP-001)."""
    from mnemosyne.mcp.server import run_stdio

    run_stdio(args.db_path)
    return 0


def _run_install(args: argparse.Namespace) -> int:
    """Print the stdio config snippet for the requested client (REQ-MCP-010)."""
    snippets = _install_snippets()
    client = args.client
    if client not in snippets:
        print(
            f"Error: unknown client '{client}'. Supported: {', '.join(sorted(snippets))}",
            file=sys.stderr,
        )
        return 2

    entry = snippets[client]
    config = entry["config"]
    rendered = json.dumps(config, indent=2)

    if args.apply:
        # REQ-MCP-010: without --apply we never write outside the repo. With
        # --apply we still only write to an explicit user-supplied path so we
        # never silently touch a global config file.
        target = Path(args.apply).expanduser()
        if target.exists() and not args.force:
            print(
                f"Error: {target} exists; use --force to overwrite, or remove the file.",
                file=sys.stderr,
            )
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {target}")
        return 0

    print(f"# mnemosyne MCP config for {client}")
    if entry.get("note"):
        print(f"# {entry['note']}")
    if entry.get("file"):
        print(f"# Config file: {entry['file']}")
    print(rendered)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``mnemosyne mcp``."""
    parser = argparse.ArgumentParser(
        prog="mnemosyne mcp",
        description="MCP server for mnemosyne (SPEC-MCP-001).",
    )
    sub = parser.add_subparsers(dest="mcp_command")

    serve_p = sub.add_parser(
        "serve",
        help="Run the MCP stdio server (JSON-RPC over stdin/stdout).",
    )
    serve_p.add_argument("--db-path", default=None, help="Knowledge graph database path.")

    install_p = sub.add_parser(
        "install",
        help="Print an MCP client config snippet (REQ-MCP-010).",
        description=(
            "Print a stdio config snippet for Claude Desktop, Hermes, or OpenClaw. "
            "Does NOT write any file unless --apply is given."
        ),
    )
    install_p.add_argument(
        "--client",
        required=True,
        choices=["claude-desktop", "hermes", "openclaw"],
        help="Target MCP client.",
    )
    install_p.add_argument(
        "--apply",
        default=None,
        help="Write the snippet to this path (no writes without --apply).",
    )
    install_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing file when --apply is used.",
    )

    args = parser.parse_args(argv)
    if args.mcp_command is None:
        parser.print_help()
        return 0
    if args.mcp_command == "serve":
        return _run_serve(args)
    if args.mcp_command == "install":
        return _run_install(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
