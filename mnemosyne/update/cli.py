"""
CLI handler for mnemosyne upgrade command.

Provides command-line interface for checking and installing updates.
"""

import argparse
import json
import sys

from mnemosyne.update.checker import UpdateChecker, format_update_info
from mnemosyne.update.detector import detect_installation_type, detect_platform
from mnemosyne.update.updater import update_current


def cmd_upgrade(args) -> int:
    """
    Execute the upgrade command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Detect installation type
    install_info = detect_installation_type()

    # Check for updates
    checker = UpdateChecker()
    update_info = checker.check_for_updates(install_info.version)

    # Format and display check result
    if args.format == "json":
        print(
            json.dumps(
                {
                    "installation_type": install_info.type,
                    "current_version": install_info.version,
                    "has_update": update_info.has_update,
                    "latest_version": update_info.latest_version,
                    "release_url": update_info.release_url,
                }
            )
        )
    else:
        print(f"Installation type: {install_info.type}")
        print(f"Current version: {install_info.version}")
        print()
        print(format_update_info(update_info, "text"))

    # Check-only mode
    if args.check_only:
        return 0

    # No update available
    if not update_info.has_update:
        return 0

    # Auto-confirm mode
    if not args.yes:
        response = input("Do you want to update? [y/N] ")
        if response.lower() not in ("y", "yes"):
            print("Update cancelled.")
            return 0

    # Perform update
    print("\nUpdating...")
    result = update_current(confirm=False)

    if result.success:
        print(f"\n✓ {result.message}")

        if result.backup_path:
            print(f"  Backup saved to: {result.backup_path}")

        return 0
    else:
        print(f"\n✗ {result.message}")
        return 1


def create_upgrade_parser(subparsers) -> argparse.ArgumentParser:
    """
    Create the upgrade subcommand parser.

    Args:
        subparsers: The subparsers object from the main CLI

    Returns:
        The configured argument parser
    """
    upgrade = subparsers.add_parser(
        "upgrade",
        help="Check for and install updates from GitHub Releases",
        description="Upgrade Mnemosyne to the latest version from GitHub Releases. "
        "Supports binary, pip, and development installations.",
        epilog="""
Examples:
  mnemosyne upgrade --check-only       # Check for updates without installing
  mnemosyne upgrade --yes               # Auto-confirm update
  mnemosyne upgrade --format json       # JSON output for scripts

Installation types:
  - Binary: Downloads and replaces the binary (Linux/macOS)
  - pip: Runs 'pip install --upgrade mnemosyne-kg'
  - Dev: Shows manual update instructions
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    upgrade.add_argument(
        "--check-only",
        action="store_true",
        help="Check for updates without installing",
    )

    upgrade.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    upgrade.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt and auto-update",
    )

    upgrade.set_defaults(func=cmd_upgrade)

    return upgrade
