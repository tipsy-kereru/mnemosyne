"""Regression tests for `mnemosyne upgrade` binary-installation platform detection.

Bug: update_current() used to pass ``install_type.install_path.name`` (the
install *directory* name, e.g. ``bin``) to ``get_asset_for_platform`` instead
of the actual platform tag (e.g. ``darwin-arm64``). Since release assets are
named ``mnemosyne-<os>-<arch>``, a directory named ``bin`` never matches any
asset, so every binary-install upgrade failed with
"No binary found for platform bin" regardless of the real platform or
available assets.
"""

from pathlib import Path
from unittest.mock import patch

from mnemosyne.update.checker import Asset, UpdateInfo
from mnemosyne.update.detector import InstallationType, PlatformInfo
from mnemosyne.update.updater import UpdateResult, update_current


def _update_info(assets: list[Asset]) -> UpdateInfo:
    return UpdateInfo(
        has_update=True,
        current_version="0.7.0",
        latest_version="0.10.0",
        release_url="https://example.test/releases/v0.10.0",
        release_name="v0.10.0",
        release_notes=None,
        published_at="2026-08-06",
        assets=assets,
    )


def _binary_install(install_dir_name: str) -> InstallationType:
    return InstallationType(
        type="binary",
        version="0.7.0",
        executable_path=Path(f"/Users/kereru/.local/{install_dir_name}/mnemosyne"),
        install_path=Path(f"/Users/kereru/.local/{install_dir_name}"),
    )


def test_binary_upgrade_matches_real_platform_not_install_dir_name():
    """The install directory name (e.g. 'bin') must never be used as the
    platform tag; the actual OS/arch platform must be resolved instead."""
    darwin_asset = Asset(
        name="mnemosyne-darwin-arm64",
        url="https://example.test/asset/1",
        size=1234,
        download_url="https://example.test/download/mnemosyne-darwin-arm64",
        content_type="application/octet-stream",
    )

    with patch(
        "mnemosyne.update.detector.detect_installation_type",
        return_value=_binary_install("bin"),
    ), patch(
        "mnemosyne.update.detector.detect_platform",
        return_value=PlatformInfo(os="darwin", arch="arm64", asset_tag="darwin-arm64"),
    ), patch(
        "mnemosyne.update.checker.UpdateChecker.check_for_updates",
        return_value=_update_info([darwin_asset]),
    ), patch(
        "mnemosyne.update.updater.BinaryUpdater.update",
        return_value=UpdateResult(success=True, message="updated"),
    ) as mock_update:
        result = update_current(confirm=False)

    assert result.success is True
    # The resolved asset passed to BinaryUpdater.update must be the real
    # platform's asset, not something derived from the install dir name.
    called_asset = mock_update.call_args[0][0]
    assert called_asset.name == "mnemosyne-darwin-arm64"


def test_binary_upgrade_reports_missing_asset_using_real_platform_tag():
    """When no matching asset exists, the error must name the actual
    platform tag, not the install directory name."""
    linux_asset = Asset(
        name="mnemosyne-linux-x86_64",
        url="https://example.test/asset/2",
        size=1234,
        download_url="https://example.test/download/mnemosyne-linux-x86_64",
        content_type="application/octet-stream",
    )

    with patch(
        "mnemosyne.update.detector.detect_installation_type",
        return_value=_binary_install("bin"),
    ), patch(
        "mnemosyne.update.detector.detect_platform",
        return_value=PlatformInfo(os="darwin", arch="arm64", asset_tag="darwin-arm64"),
    ), patch(
        "mnemosyne.update.checker.UpdateChecker.check_for_updates",
        return_value=_update_info([linux_asset]),
    ):
        result = update_current(confirm=False)

    assert result.success is False
    assert "darwin-arm64" in result.message
    assert "bin" not in result.message.split("platform ")[-1]
