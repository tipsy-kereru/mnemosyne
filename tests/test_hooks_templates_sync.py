"""Assert bundled template constants stay in sync with the template files.

The hook templates ship both as files under ``mnemosyne/hooks/templates/``
(for pip installs, where the host agent executes them by path) and as string
constants in ``mnemosyne/hooks/_templates_bundled.py`` (so the PyOxidizer
frozen binary can read them without ``importlib.resources``). This test
catches drift between the two.
"""
from __future__ import annotations

from pathlib import Path

from mnemosyne.hooks._templates_bundled import TEMPLATES

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "mnemosyne" / "hooks" / "templates"


def test_every_bundled_template_has_a_matching_file() -> None:
    missing = [name for name in TEMPLATES if not (TEMPLATES_DIR / name).is_file()]
    assert not missing, f"bundled templates without a file: {missing}"


def test_bundled_content_matches_files() -> None:
    drift = []
    for name, bundled in TEMPLATES.items():
        on_disk = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        if bundled != on_disk:
            drift.append(name)
    assert not drift, (
        "bundled templates drifted from files — re-copy the file contents into "
        f"mnemosyne/hooks/_templates_bundled.py for: {drift}"
    )
