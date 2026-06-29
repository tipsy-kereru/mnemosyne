"""
Mnemosyne self-update module.

Provides functionality to check for and install updates from GitHub Releases.
Supports multiple installation types: binary, pip, and development/source.
"""

from mnemosyne.update.detector import (
    InstallationType,
    detect_installation_type,
    detect_platform,
)
from mnemosyne.update.checker import UpdateChecker, UpdateInfo
from mnemosyne.update.updater import (
    BinaryUpdater,
    PipUpdater,
    DevUpdater,
    UpdateResult,
)

__all__ = [
    # Detector
    "InstallationType",
    "detect_installation_type",
    "detect_platform",
    # Checker
    "UpdateChecker",
    "UpdateInfo",
    # Updater
    "BinaryUpdater",
    "PipUpdater",
    "DevUpdater",
    "UpdateResult",
]
