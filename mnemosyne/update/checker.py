"""
Update checker for Mnemosyne self-update.

Checks GitHub Releases for the latest version and compares with current version.
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

# GitHub API configuration
BASE_URL = "https://api.github.com"
REPO_OWNER = "tipsy-kereru"
REPO_NAME = "mnemosyne"
API_VERSION = "2022-11-28"


@dataclass
class Asset:
    """Represents a release asset (binary package)."""

    name: str
    url: str
    size: int
    download_url: str
    content_type: str


@dataclass
class UpdateInfo:
    """Information about available update."""

    has_update: bool
    current_version: str
    latest_version: str
    release_url: Optional[str]
    release_name: Optional[str]
    release_notes: Optional[str]
    published_at: Optional[str]
    assets: list[Asset]


class UpdateChecker:
    """
    Checks GitHub Releases for Mnemosyne updates.

    Uses GitHub API to fetch the latest release and compare versions.
    """

    def __init__(
        self,
        owner: str = REPO_OWNER,
        repo: str = REPO_NAME,
        base_url: str = BASE_URL,
    ):
        """
        Initialize the update checker.

        Args:
            owner: GitHub repository owner (default: tipsy-kereru)
            repo: GitHub repository name (default: mnemosyne)
            base_url: GitHub API base URL (default: https://api.github.com)
        """
        self.owner = owner
        self.repo = repo
        self.base_url = base_url.rstrip("/")

    def check_for_updates(self, current_version: str) -> UpdateInfo:
        """
        Check if a newer version is available on GitHub Releases.

        Args:
            current_version: Current Mnemosyne version string

        Returns:
            UpdateInfo with update availability and release details
        """
        try:
            latest = self._fetch_latest_release()
            has_update = self._compare_versions(current_version, latest["tag_name"])

            # Parse assets
            assets = []
            for asset in latest.get("assets", []):
                assets.append(
                    Asset(
                        name=asset["name"],
                        url=asset.get("url", ""),
                        size=asset.get("size", 0),
                        download_url=asset.get("browser_download_url", ""),
                        content_type=asset.get("content_type", ""),
                    )
                )

            return UpdateInfo(
                has_update=has_update,
                current_version=current_version,
                latest_version=latest["tag_name"].lstrip("v"),
                release_url=latest.get("html_url"),
                release_name=latest.get("name"),
                release_notes=latest.get("body"),
                published_at=latest.get("published_at"),
                assets=assets,
            )
        except Exception as e:
            # On error, assume no update available
            return UpdateInfo(
                has_update=False,
                current_version=current_version,
                latest_version=current_version,
                release_url=None,
                release_name=None,
                release_notes=None,
                published_at=None,
                assets=[],
            )

    def _fetch_latest_release(self) -> dict:
        """
        Fetch the latest release from GitHub API.

        Returns:
            JSON response from GitHub Releases API

        Raises:
            urllib.error.URLError: If API request fails
        """
        url = f"{self.base_url}/repos/{self.owner}/{self.repo}/releases/latest"

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "mnemosyne-update-checker",
        }

        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read()
            return json.loads(data.decode("utf-8"))

    def _compare_versions(self, current: str, latest: str) -> bool:
        """
        Compare two version strings to check if latest is newer.

        Args:
            current: Current version string
            latest: Latest version string (may include 'v' prefix)

        Returns:
            True if latest is newer than current
        """
        # Strip 'v' prefix and common suffixes
        current_clean = current.lstrip("v").split("+")[0].split("-")[0]
        latest_clean = latest.lstrip("v").split("+")[0].split("-")[0]

        try:
            current_parts = [int(x) for x in current_clean.split(".")]
            latest_parts = [int(x) for x in latest_clean.split(".")]

            # Pad shorter version with zeros
            max_len = max(len(current_parts), len(latest_parts))
            current_parts += [0] * (max_len - len(current_parts))
            latest_parts += [0] * (max_len - len(latest_parts))

            # Compare each part
            for c, l in zip(current_parts, latest_parts):
                if l > c:
                    return True
                if l < c:
                    return False

            return False  # Versions are equal
        except (ValueError, AttributeError):
            # If version parsing fails, compare as strings
            return latest_clean > current_clean

    def get_asset_for_platform(self, assets: list[Asset], platform_tag: str) -> Optional[Asset]:
        """
        Find the appropriate binary asset for the current platform.

        Args:
            assets: List of release assets
            platform_tag: Platform tag like "linux-x86_64" or "darwin-arm64"

        Returns:
            Matching Asset or None if not found
        """
        # Look for exact match first
        for asset in assets:
            if platform_tag in asset.name:
                return asset

        # Fallback: look for partial match (e.g., darwin instead of darwin-arm64)
        platform_prefix = platform_tag.split("-")[0]
        for asset in assets:
            if platform_prefix in asset.name:
                return asset

        return None


def format_update_info(info: UpdateInfo, format_type: str = "text") -> str:
    """
    Format update information for display.

    Args:
        info: UpdateInfo from check_for_updates
        format_type: "text" or "json"

    Returns:
        Formatted string
    """
    if format_type == "json":
        return json.dumps(
            {
                "has_update": info.has_update,
                "current_version": info.current_version,
                "latest_version": info.latest_version,
                "release_url": info.release_url,
                "release_name": info.release_name,
                "published_at": info.published_at,
            },
            indent=2,
        )

    # Text format
    if not info.has_update:
        return f"✓ Already up to date (version {info.current_version})"

    lines = [
        f"Update available: {info.current_version} → {info.latest_version}",
        "",
    ]

    if info.release_name:
        lines.append(f"Release: {info.release_name}")

    if info.published_at:
        from datetime import datetime

        try:
            pub_date = datetime.fromisoformat(info.published_at.replace("Z", "+00:00"))
            lines.append(f"Published: {pub_date.strftime('%Y-%m-%d')}")
        except ValueError:
            lines.append(f"Published: {info.published_at}")

    if info.release_url:
        lines.append(f"URL: {info.release_url}")

    # Show available assets
    if info.assets:
        lines.append("")
        lines.append("Available assets:")
        for asset in info.assets:
            size_mb = asset.size / (1024 * 1024)
            lines.append(f"  - {asset.name} ({size_mb:.1f} MB)")

    # Show first few lines of release notes
    if info.release_notes:
        lines.append("")
        note_lines = info.release_notes.split("\n")[:5]
        lines.append("Release notes:")
        lines.extend(f"  {line}" for line in note_lines)
        if len(info.release_notes.split("\n")) > 5:
            lines.append("  ...")

    return "\n".join(lines)
