"""Build the Windows x86_64 standalone executable with Python 3.11 and PyInstaller.

Run in a dedicated build environment with maturin and pyinstaller==6.22.2.
The resulting EXE includes the interpreter, native extensions and package data.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build Windows x86_64 on a native Windows x64 runner")
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("The Windows release toolchain uses CPython 3.11")
    root = Path(__file__).resolve().parents[1]
    build = root / "build" / "windows"
    wheels = build / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)

    def run(*arguments, cwd=root):
        subprocess.run([sys.executable, *map(str, arguments)], cwd=cwd, check=True)

    run(
        "-m",
        "maturin",
        "build",
        "--release",
        "--interpreter",
        sys.executable,
        "--out",
        wheels,
        cwd=root / "mnemosyne-core",
    )
    candidates = list(wheels.glob("mnemosyne_core-*-cp311-*-win_amd64.whl"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one CPython 3.11 Windows core wheel, found {candidates}")
    run("-m", "pip", "install", "--force-reinstall", "--no-deps", candidates[0])
    run("-m", "pip", "install", "-r", root / "requirements-binary.txt", root)
    arguments = [
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noupx",
        "--name",
        "mnemosyne-windows-x86_64",
        "--distpath",
        str(root / "artifacts"),
        "--workpath",
        str(build / "pyinstaller"),
        "--specpath",
        str(build),
        "--paths",
        str(root),
        "--recursive-copy-metadata",
        "mnemosyne-kg",
        "--hidden-import",
        "ctypes",
        "--hidden-import",
        "mcp.server.fastmcp",
        "--collect-data",
        "mcp",
    ]
    # AnyIO inspects its own source for lazy imports. collect-all includes that
    # source as well as dynamically imported modules and schema/package data.
    for package in (
        "mnemosyne",
        "mnemosyne_core",
        "anyio",
        "jsonschema_specifications",
        "referencing",
    ):
        arguments.extend(["--collect-all", package])
    run(*arguments, root / "scripts" / "windows_entrypoint.py")


if __name__ == "__main__":
    main()
