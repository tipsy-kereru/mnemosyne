"""Extension registry client (REQ-PKG-004).

The default registry is GitHub Releases of
``tipsy-kereru/mnemosyne-ext-<name>``. Each release ships two assets:

  - ``<name>-<version>-<platform>-<python_tag>.tar.gz`` -- the payload
  - ``manifest.json`` -- signed manifest (downloaded separately so the
    payload tarball can be regenerated without rewriting the manifest)

The registry client is a thin abstraction so tests can inject a fake
``Registry`` implementation (no network) and so a future alternate
registry (S3, local file://, corporate mirror) can slot in without
touching the installer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_REGISTRY_OWNER = "tipsy-kereru"
DEFAULT_REGISTRY_REPO_FMT = "mnemosyne-ext-{name}"


class RegistryError(RuntimeError):
    """Raised when the registry cannot be reached or returns a bad response."""


@dataclass(frozen=True)
class ReleaseAsset:
    """A single downloadable asset attached to a registry release."""

    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class Release:
    """A registry release (tag + assets + manifest text)."""

    tag: str
    assets: tuple[ReleaseAsset, ...]
    manifest_json: str
    notes: str = ""


class Registry(Protocol):
    """Abstract registry surface consumed by the installer."""

    def latest_release(self, name: str) -> Release:  # pragma: no cover - iface
        ...

    def release(self, name: str, version: str) -> Release:  # pragma: no cover - iface
        ...

    def search(self, query: str | None = None) -> list[dict[str, Any]]:  # pragma: no cover
        ...

    def fetch_asset(self, asset: ReleaseAsset, dest: Path) -> None:  # pragma: no cover
        ...


class HttpGithubRegistry:
    """GitHub Releases registry client.

    Uses :mod:`urllib.request` from the stdlib to avoid adding a hard
    dependency on ``httpx``/``requests`` for extension install. The GitHub
    REST API returns JSON with ``tag_name`` and ``assets[]``; each asset
    has ``name``, ``browser_download_url``, and ``size``.
    """

    def __init__(
        self,
        owner: str = DEFAULT_REGISTRY_OWNER,
        repo_fmt: str = DEFAULT_REGISTRY_REPO_FMT,
        *,
        base_url: str = "https://api.github.com",
    ) -> None:
        self.owner = owner
        self.repo_fmt = repo_fmt
        self.base_url = base_url.rstrip("/")

    def _repo(self, name: str) -> str:
        return self.repo_fmt.format(name=name)

    def _get(self, path: str) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - trusted registry
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RegistryError(f"registry request failed: {url}: {exc}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"registry returned non-JSON: {exc}") from exc

    @staticmethod
    def _release_from_json(data: dict[str, Any]) -> Release:
        assets = tuple(
            ReleaseAsset(
                name=str(a.get("name", "")),
                url=str(a.get("browser_download_url", "")),
                size=int(a.get("size", 0) or 0),
            )
            for a in data.get("assets", [])
        )
        manifest_json = ""
        # Manifest is shipped as a release asset named manifest.json.
        for a in assets:
            if a.name == "manifest.json" and a.url:
                import urllib.request

                try:
                    with urllib.request.urlopen(a.url, timeout=30) as resp:  # noqa: S310
                        manifest_json = resp.read().decode("utf-8")
                except Exception as exc:  # pragma: no cover - network paths tested via fakes
                    raise RegistryError(f"cannot fetch manifest asset: {exc}") from exc
                break
        return Release(
            tag=str(data.get("tag_name", "")),
            assets=assets,
            manifest_json=manifest_json,
            notes=str(data.get("body", "")),
        )

    def latest_release(self, name: str) -> Release:
        repo = self._repo(name)
        return self._release_from_json(self._get(f"/repos/{self.owner}/{repo}/releases/latest"))

    def release(self, name: str, version: str) -> Release:
        repo = self._repo(name)
        tag = version if version.startswith("v") else f"v{version}"
        return self._release_from_json(
            self._get(f"/repos/{self.owner}/{repo}/releases/tags/{tag}")
        )

    def search(self, query: str | None = None) -> list[dict[str, Any]]:
        # GitHub does not expose a per-owner extension index. For the
        # first-party registry we publish a static index file in the
        # ``mnemosyne-extensions`` index repo. Out of scope to fetch live
        # here; the manager surfaces known first-party extensions.
        return _FIRST_PARTY_INDEX

    def fetch_asset(self, asset: ReleaseAsset, dest: Path) -> None:
        import urllib.request

        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(asset.url, str(dest))  # noqa: S310 - trusted registry
        except Exception as exc:  # pragma: no cover - network paths tested via fakes
            raise RegistryError(f"cannot download asset {asset.name}: {exc}") from exc


# First-party extensions shipped at GA. Used by ``search``/``info`` when no
# live registry index is available (offline default).
_FIRST_PARTY_INDEX: list[dict[str, Any]] = [
    {
        "name": "slm",
        "description": "GLiNER2 + REBEL + CPU torch for semantic entity extraction",
        "enables": ["gliner", "torch"],
        "payload_size_hint_mb": 320,
    },
    {
        "name": "pdf",
        "description": "pymupdf (fitz) for long-doc PDF parsing",
        "enables": ["fitz"],
        "payload_size_hint_mb": 20,
    },
]
