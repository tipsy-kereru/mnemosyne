"""
Installation type detector for Mnemosyne self-update.

Detects how Mnemosyne is installed (binary, pip, or development/source)
to determine the appropriate update method.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class InstallationType:
    """Represents the type and details of Mnemosyne installation."""

    type: str  # "binary", "pip", or "dev"
    version: str  # Current version
    executable_path: Optional[Path] = None  # Path to mnemosyne executable
    install_path: Optional[Path] = None  # Installation directory


@dataclass
class PlatformInfo:
    """Platform detection result for binary downloads."""

    os: str  # "linux", "darwin", "windows"
    arch: str  # "x86_64", "arm64", "aarch64"
    asset_tag: str  # "linux-x86_64", "darwin-arm64", etc.


def detect_installation_type() -> InstallationType:
    """
    Detect how Mnemosyne is currently installed.

    Detection priority:
    1. Binary: Has mnemosyne._version module + sys.frozen
    2. pip: Has importlib.metadata entry for "mnemosyne-kg"
    3. Dev/source: Returns "0.0.0+unknown" version or has .git directory

    Returns:
        InstallationType with type, version, and path information
    """
    # Try to detect binary installation
    try:
        # Binary builds have _version.py baked in at build time
        from mnemosyne._version import __version__ as version  # type: ignore

        # Check if running as frozen executable (PyOxidizer)
        if getattr(sys, "frozen", False):
            executable_path = Path(sys.executable)
            return InstallationType(
                type="binary",
                version=version,
                executable_path=executable_path,
                install_path=executable_path.parent,
            )
    except ImportError:
        pass

    # Try to detect pip installation
    try:
        from importlib.metadata import version as _pkg_version

        pip_version = _pkg_version("mnemosyne-kg")
        executable_path = Path(sys.executable)

        return InstallationType(
            type="pip",
            version=pip_version,
            executable_path=executable_path,
            install_path=executable_path.parent,
        )
    except Exception:
        pass

    # Check for development/source installation
    # Look for .git directory or unknown version
    current_dir = Path(__file__).resolve()

    # Walk up to find project root
    project_root = current_dir
    for _ in range(4):  # Limit depth to avoid infinite loops
        if (project_root / ".git").exists():
            break
        parent = project_root.parent
        if parent == project_root:
            break
        project_root = parent

    is_git_repo = (project_root / ".git").exists()

    # Try to get version from __init__.py (may return "0.0.0+unknown")
    try:
        from mnemosyne import __version__ as version
    except ImportError:
        version = "0.0.0+unknown"

    return InstallationType(
        type="dev",
        version=version,
        executable_path=Path(sys.argv[0]) if sys.argv else None,
        install_path=project_root if is_git_repo else None,
    )


def detect_platform() -> PlatformInfo:
    """
    Detect the current platform for binary asset selection.

    Returns:
        PlatformInfo with OS, architecture, and asset tag
    """
    import platform

    os_name = sys.platform.lower()
    machine = platform.machine().lower()

    # Normalize OS names
    if os_name.startswith("linux"):
        os_norm = "linux"
    elif os_name.startswith("darwin"):
        os_norm = "darwin"
    elif os_name.startswith("win") or os_name in ("msys", "cygwin"):
        os_norm = "windows"
    else:
        os_norm = os_name

    # Normalize architecture names
    # Handle Rosetta (x86_64 on arm64 macOS)
    if os_norm == "darwin" and machine == "x86_64":
        # Check if actually running on arm64
        try:
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "hw.optional.arm64"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "1":
                machine = "arm64"
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

    # Map to asset tag names
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "aarch64",
        "armv7l": "arm",
    }

    arch_norm = arch_map.get(machine, machine)

    # Build asset tag
    asset_tag = f"{os_norm}-{arch_norm}"

    return PlatformInfo(
        os=os_norm,
        arch=arch_norm,
        asset_tag=asset_tag,
    )


def get_binary_asset_name() -> str:
    """
    Get the expected binary asset name for the current platform.

    Returns:
        Asset name like "mnemosyne-linux-x86_64" or "mnemosyne-darwin-arm64"
    """
    platform = detect_platform()
    return f"mnemosyne-{platform.asset_tag}"
