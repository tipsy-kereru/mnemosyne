"""
Updater implementations for different installation types.

Provides update mechanisms for binary, pip, and development installations.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mnemosyne.update.checker import Asset


@dataclass
class UpdateResult:
    """Result of an update operation."""

    success: bool
    message: str
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    backup_path: Optional[Path] = None


class BinaryUpdater:
    """
    Updates binary installations by downloading from GitHub Releases.

    Includes backup and rollback functionality.
    """

    def __init__(self, executable_path: Path, install_dir: Path):
        """
        Initialize the binary updater.

        Args:
            executable_path: Path to current mnemosyne executable
            install_dir: Directory where mnemosyne is installed
        """
        self.executable_path = executable_path
        self.install_dir = install_dir
        self.backup_path = executable_path.with_suffix(".backup")

    def update(self, asset: Asset, confirm: bool = True) -> UpdateResult:
        """
        Update the binary installation.

        Args:
            asset: Release asset to download
            confirm: If True, requires user confirmation (not used here, handled by CLI)

        Returns:
            UpdateResult with success status and message
        """
        # Check write permissions
        if not self._check_permissions():
            return UpdateResult(
                success=False,
                message="Insufficient permissions. Try running with sudo or as administrator.",
            )

        # Create backup
        try:
            if self.executable_path.exists():
                shutil.copy2(self.executable_path, self.backup_path)
        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"Failed to create backup: {e}",
            )

        # Download new version
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix="_new") as tmp_file:
                tmp_path = Path(tmp_file.name)

                # Download with progress
                self._download_with_progress(asset.download_url, tmp_path)

                # Verify download
                if not tmp_path.stat().st_size > 0:
                    raise ValueError("Downloaded file is empty")

                # Replace executable
                try:
                    shutil.copy2(tmp_path, self.executable_path)
                    os.chmod(self.executable_path, 0o755)  # Make executable
                except Exception as e:
                    # Rollback on failure
                    self._rollback()
                    raise

                # Clean up
                tmp_path.unlink(missing_ok=True)

                return UpdateResult(
                    success=True,
                    message=f"Successfully updated to {asset.name}",
                    backup_path=self.backup_path,
                )

        except Exception as e:
            self._rollback()
            return UpdateResult(
                success=False,
                message=f"Update failed: {e}",
            )

    def _check_permissions(self) -> bool:
        """Check if we have write permissions to the install directory."""
        return os.access(self.install_dir, os.W_OK)

    def _download_with_progress(self, url: str, dest_path: Path) -> None:
        """Download file with progress indication."""
        def report_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, downloaded * 100 / total_size)
                if downloaded % (1024 * 1024) == 0 or percent == 100:  # Log every MB
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    print(f"  Downloading: {mb_downloaded:.1f}/{mb_total:.1f} MB ({percent:.0f}%)")

        urllib.request.urlretrieve(url, dest_path, reporthook=report_progress)

    def _rollback(self) -> None:
        """Restore from backup if update failed."""
        if self.backup_path.exists():
            try:
                shutil.copy2(self.backup_path, self.executable_path)
                os.chmod(self.executable_path, 0o755)
            except Exception:
                pass  # Best effort rollback

    def cleanup_backup(self) -> None:
        """Remove backup file after successful update."""
        if self.backup_path.exists():
            self.backup_path.unlink()


class PipUpdater:
    """
    Updates pip installations using pip install --upgrade.
    """

    def update(self, confirm: bool = True) -> UpdateResult:
        """
        Update the pip installation.

        Args:
            confirm: If True, requires user confirmation

        Returns:
            UpdateResult with success status and message
        """
        try:
            # Get current version before update
            try:
                from importlib.metadata import version

                current_version = version("mnemosyne-kg")
            except Exception:
                current_version = "unknown"

            # Run pip install --upgrade
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--break-system-packages", "mnemosyne-kg"]

            if confirm:
                print(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd, capture_output=True, text=True, check=False
            )

            if result.returncode == 0:
                try:
                    new_version = version("mnemosyne-kg")
                except Exception:
                    new_version = "unknown"

                return UpdateResult(
                    success=True,
                    message="Successfully updated via pip",
                    previous_version=current_version,
                    new_version=new_version,
                )
            else:
                return UpdateResult(
                    success=False,
                    message=f"pip install failed: {result.stderr}",
                )

        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"Update failed: {e}",
            )


class DevUpdater:
    """
    Provides update instructions for development/source installations.

    Does not perform automatic update, but guides the user.
    """

    def update(self, confirm: bool = True) -> UpdateResult:
        """
        Show update instructions for development installations.

        Args:
            confirm: Not used, always shows instructions

        Returns:
            UpdateResult with instructions
        """
        # Check if in git repository
        import subprocess

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                cwd=Path(__file__).parent.parent.parent,
            )
            is_git_repo = result.returncode == 0
        except Exception:
            is_git_repo = False

        if is_git_repo:
            message = """Development installation detected.

To update:
    git pull
    pip install -e ".[all]"

Or reinstall:
    pip install --force-reinstall --no-deps "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
"""
        else:
            message = """Development installation detected.

To update:
    pip install --upgrade "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne.git"
"""

        return UpdateResult(
            success=True,  # Success means instructions were provided
            message=message,
        )


def update_current(confirm: bool = True) -> UpdateResult:
    """
    Update the current Mnemosyne installation regardless of type.

    Detects installation type and uses the appropriate updater.

    Args:
        confirm: If True, requires user confirmation

    Returns:
        UpdateResult from the appropriate updater
    """
    from mnemosyne.update.detector import detect_installation_type
    from mnemosyne.update.checker import UpdateChecker

    # Detect installation type
    install_type = detect_installation_type()

    # Get current version
    current_version = install_type.version

    # Check for updates
    checker = UpdateChecker()
    update_info = checker.check_for_updates(current_version)

    if not update_info.has_update:
        return UpdateResult(
            success=True,
            message=f"Already up to date (version {current_version})",
        )

    # Select appropriate updater
    if install_type.type == "binary":
        if not install_type.executable_path or not install_type.install_path:
            return UpdateResult(
                success=False,
                message="Cannot determine binary installation path",
            )

        platform = checker.get_asset_for_platform(
            update_info.assets, install_type.install_path.name
        )

        if not platform:
            return UpdateResult(
                success=False,
                message=f"No binary found for platform {install_type.install_path.name}",
            )

        updater = BinaryUpdater(
            executable_path=install_type.executable_path,
            install_dir=install_type.install_path,
        )
        return updater.update(platform, confirm)

    elif install_type.type == "pip":
        updater = PipUpdater()
        return updater.update(confirm)

    else:  # dev
        updater = DevUpdater()
        return updater.update(confirm)
