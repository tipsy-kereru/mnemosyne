"""Generate roff man pages from the mnemosyne argparse tree.

Walks ``mnemosyne.cli.build_parser()`` and emits one ``.1`` roff file per
leaf subcommand to ``docs/man/``. Scaffold for SPEC-PACKAGE-001 (REQ-PKG-008);
CI wiring is a follow-up (ISSUE-0009/D).

Usage::

    python scripts/gen_manpages.py
    man -l docs/man/mnemosyne-ingest-add.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _iter_leaf_subparsers(
    parser: argparse.ArgumentParser,
    prefix: str = "mnemosyne",
):
    """Yield ``(name_slug, parser)`` tuples for every leaf subcommand.

    A leaf is a subparser that either has no subparsers of its own or whose
    subparsers have no choices. We recurse through one level of grouping
    (``group verb``) which is the maximum depth mnemosyne uses.
    Legacy deprecation aliases are skipped (they re-export new handlers).
    """
    sub_action = None
    for action in parser._actions:  # noqa: SLF001 — argparse has no public walk API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            sub_action = action
            break
    if sub_action is None:
        return

    for name, sub in sub_action.choices.items():
        # Skip legacy deprecation aliases — they re-export new handlers.
        if sub.get_default("_deprecated_to"):
            continue
        nested = None
        for action in sub._actions:  # noqa: SLF001
            if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
                nested = action
                break
        if nested and nested.choices:
            for verb, verb_sub in nested.choices.items():
                slug = f"{prefix}-{name}-{verb}"
                yield slug, verb_sub
        else:
            slug = f"{prefix}-{name}"
            yield slug, sub


def _escape_roff(text: str) -> str:
    """Escape characters that are special in roff."""
    return text.replace("\\", "\\\\").replace("-", "\\-")


def _format_options(parser: argparse.ArgumentParser) -> str:
    """Render the parser's optional/positional arguments as roff lines."""
    lines: list[str] = []
    for action in parser._actions:  # noqa: SLF001
        if action is parser._actions[0] and isinstance(action, argparse._HelpAction):
            # Skip the implicit -h/--help unless it's the only action.
            continue
        opts = []
        if action.option_strings:
            opts.append(", ".join(action.option_strings))
        else:
            metavar = action.metavar or action.dest
            opts.append(metavar)
        help_text = (action.help or "").strip()
        # Trailing placeholder like "(default: daily)" should survive.
        line = f'.TP\n\\fB{_escape_roff(opts[0])}\\fR'
        if help_text:
            line += f"\n{_escape_roff(help_text)}"
        lines.append(line)
    return "\n".join(lines)


def _render_roff(slug: str, parser: argparse.ArgumentParser) -> str:
    """Build a complete roff man-page body for a leaf parser."""
    name = slug.replace("mnemosyne-", "mnemosyne ")
    description = (parser.description or "").strip() or name
    options_block = _format_options(parser) or "\\fB-h, --help\\fR\nShow this help and exit."
    return (
        f'.TH {slug.upper()} 1 "{_today()}" "mnemosyne" "Mnemosyne CLI"\n'
        f'.SH NAME\n{name} \\- {_escape_roff(description.splitlines()[0])}\n'
        f'.SH SYNOPSIS\n\\fB{name}\\fR [options]\n'
        f'.SH DESCRIPTION\n{_escape_roff(description)}\n'
        f'.SH OPTIONS\n{options_block}\n'
        f'.SH SEE ALSO\nmnemosyne(1)\n'
    )


def _today() -> str:
    from datetime import date
    return date.today().strftime("%Y-%m-%d")


def generate(output_dir: Path) -> list[Path]:
    """Write all man pages to ``output_dir``. Returns list of written paths."""
    from mnemosyne.cli import build_parser

    output_dir.mkdir(parents=True, exist_ok=True)
    root = build_parser()
    written: list[Path] = []
    for slug, parser in _iter_leaf_subparsers(root):
        path = output_dir / f"{slug}.1"
        path.write_text(_render_roff(slug, parser), encoding="utf-8")
        written.append(path)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_manpages",
        description="Generate roff man pages from the mnemosyne CLI tree.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("docs/man"),
        help="Output directory for .1 roff files (default: docs/man)",
    )
    args = parser.parse_args(argv)
    written = generate(args.output_dir)
    print(f"Wrote {len(written)} man pages to {args.output_dir}")
    for path in sorted(written):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
