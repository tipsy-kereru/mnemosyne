"""Verb handlers for the ``mnemosyne extension`` command group.

These are thin wrappers over :class:`ExtensionManager` that translate
parsed argparse namespaces into manager calls and format output for the
terminal (text by default, JSON with ``--format json``).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

from mnemosyne.extensions.installer import (
    ExtensionManager,
    ExtensionNotFoundError,
    IntegrityError,
)
from mnemosyne.extensions.manifest import ManifestError
from mnemosyne.extensions.registry import RegistryError


def _format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"  # pragma: no cover


def _make_manager(args: Any) -> ExtensionManager:
    return ExtensionManager()


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def cmd_install(args: Any) -> int:
    manager = _make_manager(args)
    names: Sequence[str] = args.name if isinstance(args.name, list) else [args.name]
    results: list[dict[str, Any]] = []
    failed = False
    for name in names:
        try:
            inst = manager.install(name, version=getattr(args, "version", None), force=args.force)
            results.append(
                {
                    "name": inst.name,
                    "version": inst.version,
                    "path": str(inst.path),
                    "status": "installed",
                }
            )
        except (IntegrityError, ManifestError) as exc:
            failed = True
            results.append({"name": name, "status": "error", "error": str(exc)})
        except RegistryError as exc:
            failed = True
            results.append({"name": name, "status": "error", "error": str(exc)})
    if getattr(args, "format", "text") == "json":
        _print_json(results)
    else:
        for r in results:
            if r["status"] == "installed":
                print(f"installed {r['name']} {r['version']} -> {r['path']}")
            else:
                print(f"error: {r['name']}: {r['error']}", file=sys.stderr)
    return 1 if failed else 0


def cmd_list(args: Any) -> int:
    manager = _make_manager(args)
    installed = manager.list_installed()
    if getattr(args, "format", "text") == "json":
        _print_json(
            [
                {
                    "name": i.name,
                    "version": i.version,
                    "path": str(i.path),
                    "source": i.manifest.signer or "registry",
                }
                for i in installed
            ]
        )
        return 0
    if not installed:
        print("no extensions installed")
        return 0
    print(f"{'NAME':<16} {'VERSION':<12} {'SOURCE':<16} PATH")
    for i in installed:
        source = i.manifest.signer or "registry"
        print(f"{i.name:<16} {i.version:<12} {source:<16} {i.path}")
    return 0


def cmd_remove(args: Any) -> int:
    manager = _make_manager(args)
    names: Sequence[str] = args.name if isinstance(args.name, list) else [args.name]
    results: list[dict[str, Any]] = []
    failed = False
    for name in names:
        try:
            res = manager.remove(name)
            results.append({**res, "status": "removed"})
        except ExtensionNotFoundError as exc:
            failed = True
            results.append({"name": name, "status": "error", "error": str(exc)})
    if getattr(args, "format", "text") == "json":
        _print_json(results)
    else:
        for r in results:
            if r["status"] == "removed":
                print(
                    f"removed {r['name']} (versions: {', '.join(r['removed_versions']) or 'none'})"
                )
            else:
                print(f"error: {r['name']}: {r['error']}", file=sys.stderr)
    return 1 if failed else 0


def cmd_upgrade(args: Any) -> int:
    manager = _make_manager(args)
    results = manager.upgrade(
        name=args.name if not args.all else None, all_=args.all
    )
    if getattr(args, "format", "text") == "json":
        _print_json(results)
        return 0
    for r in results:
        status = r.get("status")
        if status == "up-to-date":
            print(f"{r['name']}: up-to-date ({r['version']})")
        elif status == "upgraded":
            frm = r.get("from") or "(none)"
            print(f"{r['name']}: upgraded {frm} -> {r['to']}")
        else:
            print(f"{r['name']}: {r.get('error', status)}", file=sys.stderr)
    return 0


def cmd_search(args: Any) -> int:
    manager = _make_manager(args)
    entries = manager.search(query=args.query)
    if getattr(args, "format", "text") == "json":
        _print_json(entries)
        return 0
    if not entries:
        print("no extensions found")
        return 0
    print(f"{'NAME':<12} {'DESCRIPTION':<48} ENABLES")
    for e in entries:
        enables = ",".join(e.get("enables", []))
        desc = str(e.get("description", ""))[:48]
        print(f"{e.get('name', ''):<12} {desc:<48} {enables}")
    return 0


def cmd_info(args: Any) -> int:
    manager = _make_manager(args)
    try:
        info = manager.info(args.name)
    except ExtensionNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "format", "text") == "json":
        _print_json(info)
        return 0
    print(f"name:      {info['name']}")
    print(f"installed: {info.get('installed', False)}")
    if info.get("installed"):
        print(f"version:   {info['version']}")
        print(f"path:      {info['path']}")
        print(f"platform:  {info.get('platform', '')}  python: {info.get('python_tag', '')}")
        print(f"size:      {_format_bytes(info.get('size_bytes', 0))}")
        print(f"enables:   {', '.join(info.get('enables', []))}")
        print(f"signer:    {info.get('signer', '')}")
        print(f"files:     {len(info.get('files', []))} declared")
    else:
        print(f"enables:   {', '.join(info.get('enables', []))}")
        print(f"hint:      {info.get('description', '')}")
    return 0


def cmd_group(args: Any) -> int:
    """Print help when ``mnemosyne extension`` is invoked with no verb."""
    print("Usage: mnemosyne extension <install|list|remove|upgrade|search|info> [options]", file=sys.stderr)
    return 2


__all__ = [
    "cmd_install",
    "cmd_list",
    "cmd_remove",
    "cmd_upgrade",
    "cmd_search",
    "cmd_info",
    "cmd_group",
]
