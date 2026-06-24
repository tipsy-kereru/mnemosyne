"""Tests for the extension sidecar mechanism (ISSUE-0007 / SPEC-PACKAGE-001 PACKAGE-B).

Coverage:
- Each verb (install / list / remove / upgrade / search / info) via a fake
  registry (no network).
- Integrity (REQ-PKG-010): SHA mismatch, corruption, manifest tamper,
  downgrade refusal, rollback (no partial install).
- Runtime sys.path loader (REQ-PKG-003): inject, highest-semver-wins,
  removed-extension-excluded, corrupt-manifest-skipped.
- E2E ``extension install slm`` with a mocked payload tarball.

The fake registry builds an in-memory tarball + manifest so the installer's
download/verify/extract path is exercised end-to-end without touching the
network.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any, Optional

import pytest

from mnemosyne.extensions.installer import (
    ExtensionManager,
    ExtensionNotFoundError,
    IntegrityError,
)
from mnemosyne.extensions.loader import load_installed_extensions
from mnemosyne.extensions.manifest import (
    ExtensionManifest,
    ManifestError,
    sha256_file,
)
from mnemosyne.extensions.registry import (
    Release,
    ReleaseAsset,
    Registry,
    RegistryError,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _build_tarball(files: dict[str, bytes]) -> bytes:
    """Build an in-memory .tar.gz containing ``files`` (relpath -> bytes)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, data in files.items():
            info = tarfile.TarInfo(name=relpath)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeRegistry:
    """In-memory registry serving pre-built releases.

    ``releases`` maps ``(name, version)`` -> dict(manifest=..., payload=bytes).
    """

    def __init__(self) -> None:
        self.releases: dict[tuple[str, str], dict[str, Any]] = {}
        self.search_index: list[dict[str, Any]] = []
        # Fetch instrumentation (for verifying asset download happened).
        self.fetched: list[str] = []

    def add_release(
        self,
        name: str,
        version: str,
        *,
        files: Optional[dict[str, bytes]] = None,
        enables: tuple[str, ...] = (),
        signer: str = "tipsy-kereru",
        platform: str = "any",
        python_tag: str = "cp311",
        tamper_manifest: Optional[str] = None,
    ) -> None:
        files = files or {}
        sha = {rel: _sha256_bytes(data) for rel, data in files.items()}
        manifest = {
            "name": name,
            "version": version,
            "platform": platform,
            "python_tag": python_tag,
            "sha256": sha,
            "enables": list(enables),
            "signer": signer,
        }
        manifest_json = json.dumps(manifest)
        if tamper_manifest is not None:
            manifest_json = tamper_manifest
        payload = _build_tarball(files)
        asset_name = f"{name}-{version}-{platform}-{python_tag}.tar.gz"
        self.releases[(name, version)] = {
            "manifest_json": manifest_json,
            "payload": payload,
            "asset_name": asset_name,
            "tag": f"v{version}",
        }

    def _release_for(self, name: str, version: Optional[str]) -> Release:
        if version is None:
            # latest = highest semver present
            versions = [v for (n, v) in self.releases if n == name]
            if not versions:
                raise RegistryError(f"no releases for {name}")
            from mnemosyne.extensions.installer import _parse_semver

            version = max(versions, key=_parse_semver)
        key = (name, version)
        if key not in self.releases:
            raise RegistryError(f"no release {name} {version}")
        rec = self.releases[key]
        asset = ReleaseAsset(
            name=rec["asset_name"],
            url=f"memory:///{name}/{version}/{rec['asset_name']}",
            size=len(rec["payload"]),
        )
        return Release(
            tag=rec["tag"],
            assets=(asset,),
            manifest_json=rec["manifest_json"],
        )

    def latest_release(self, name: str) -> Release:
        return self._release_for(name, None)

    def release(self, name: str, version: str) -> Release:
        v = version.lstrip("v")
        return self._release_for(name, v)

    def search(self, query: Optional[str] = None) -> list[dict[str, Any]]:
        entries = list(self.search_index)
        if query:
            q = query.lower()
            entries = [
                e
                for e in entries
                if q in str(e.get("name", "")).lower()
                or q in str(e.get("description", "")).lower()
            ]
        return entries

    def fetch_asset(self, asset: ReleaseAsset, dest: Path) -> None:
        # Resolve payload from the URL we synthesized.
        parts = asset.url.split("/")
        name, version = parts[-3], parts[-2]
        rec = self.releases[(name, version)]
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(rec["payload"])
        self.fetched.append(asset.name)


@pytest.fixture
def home_dir(tmp_path: Path) -> Path:
    """Isolated MNEMOSYNE_HOME so tests never touch the real ~/.mnemosyne."""
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def manager(home_dir: Path) -> ExtensionManager:
    return ExtensionManager(home=home_dir, registry=FakeRegistry())


def _make_manager_with_registry(home_dir: Path, registry: Registry) -> ExtensionManager:
    return ExtensionManager(home=home_dir, registry=registry)


# ---------------------------------------------------------------------------
# install verb
# ---------------------------------------------------------------------------


class TestInstall:
    def test_install_writes_payload_and_manifest(self, manager: ExtensionManager):
        manager.registry.add_release(
            "slm", "1.0.0", files={"gliner/__init__.py": b"# gliner stub\n"}
        )
        inst = manager.install("slm")
        assert inst.name == "slm"
        assert inst.version == "1.0.0"
        assert inst.path.is_dir()
        assert (inst.path / "manifest.json").is_file()
        assert (inst.path / "gliner" / "__init__.py").is_file()
        # Manifest persisted matches the registry manifest.
        persisted = json.loads((inst.path / "manifest.json").read_text())
        assert persisted["name"] == "slm"
        assert persisted["version"] == "1.0.0"

    def test_install_specific_version(self, manager: ExtensionManager):
        manager.registry.add_release(
            "pdf", "0.9.0", files={"fitz_stub.py": b"x"}
        )
        manager.registry.add_release(
            "pdf", "1.2.0", files={"fitz_stub.py": b"y"}
        )
        inst = manager.install("pdf", version="0.9.0")
        assert inst.version == "0.9.0"

    def test_install_rejects_downgrade_without_force(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "2.0.0", files={"a.py": b"1"})
        manager.install("slm")
        # Now offer an older version.
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"0"})
        with pytest.raises(IntegrityError, match="downgrade"):
            manager.install("slm", version="1.0.0")

    def test_install_allows_downgrade_with_force(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "2.0.0", files={"a.py": b"1"})
        manager.install("slm")
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"0"})
        inst = manager.install("slm", version="1.0.0", force=True)
        assert inst.version == "1.0.0"

    def test_install_rejects_already_installed_without_force(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        with pytest.raises(IntegrityError, match="already installed"):
            manager.install("slm")


# ---------------------------------------------------------------------------
# Integrity (REQ-PKG-010)
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_sha_mismatch_aborts_and_rolls_back(self, home_dir: Path):
        registry = FakeRegistry()
        # Manifest claims a wrong SHA for the single file.
        bad_manifest = json.dumps(
            {
                "name": "slm",
                "version": "1.0.0",
                "platform": "any",
                "python_tag": "cp311",
                "sha256": {"a.py": "0" * 64},  # wrong digest
                "enables": [],
                "signer": "tipsy-kereru",
            }
        )
        registry.add_release(
            "slm", "1.0.0", files={"a.py": b"real content"}, tamper_manifest=bad_manifest
        )
        manager = _make_manager_with_registry(home_dir, registry)
        with pytest.raises(IntegrityError, match="SHA256 mismatch|install aborted"):
            manager.install("slm")
        # Rollback: no partial install left on disk.
        assert not (manager.extensions_dir / "slm").exists()
        # Staging dir cleaned up too.
        staging = manager.extensions_dir / "slm" / "1.0.0.staging"
        assert not staging.exists()

    def test_missing_file_in_payload_aborts(self, home_dir: Path):
        registry = FakeRegistry()
        # Manifest references a file not present in the tarball.
        bad_manifest = json.dumps(
            {
                "name": "slm",
                "version": "1.0.0",
                "platform": "any",
                "python_tag": "cp311",
                "sha256": {"missing.py": _sha256_bytes(b"x")},
                "enables": [],
                "signer": "tipsy-kereru",
            }
        )
        registry.add_release(
            "slm", "1.0.0", files={}, tamper_manifest=bad_manifest
        )
        manager = _make_manager_with_registry(home_dir, registry)
        with pytest.raises(IntegrityError, match="missing file|install aborted"):
            manager.install("slm")

    def test_manifest_tamper_invalid_json_aborts(self, home_dir: Path):
        registry = FakeRegistry()
        registry.add_release(
            "slm", "1.0.0", files={"a.py": b"x"}, tamper_manifest="not json {"
        )
        manager = _make_manager_with_registry(home_dir, registry)
        with pytest.raises((ManifestError, IntegrityError)):
            manager.install("slm")

    def test_manifest_name_mismatch_aborts(self, home_dir: Path):
        registry = FakeRegistry()
        registry.add_release(
            "slm",
            "1.0.0",
            files={"a.py": b"x"},
            tamper_manifest=json.dumps(
                {
                    "name": "evil",  # claimed name != requested
                    "version": "1.0.0",
                    "platform": "any",
                    "python_tag": "cp311",
                    "sha256": {"a.py": _sha256_bytes(b"x")},
                    "enables": [],
                }
            ),
        )
        manager = _make_manager_with_registry(home_dir, registry)
        with pytest.raises(IntegrityError, match="does not match"):
            manager.install("slm")

    def test_undeclared_file_in_payload_rejected(self, home_dir: Path):
        registry = FakeRegistry()
        # Tarball has two files but manifest only declares one.
        manifest = json.dumps(
            {
                "name": "slm",
                "version": "1.0.0",
                "platform": "any",
                "python_tag": "cp311",
                "sha256": {"declared.py": _sha256_bytes(b"ok")},
                "enables": [],
                "signer": "tipsy-kereru",
            }
        )
        registry.add_release(
            "slm",
            "1.0.0",
            files={"declared.py": b"ok", "evil.py": b"malware"},
            tamper_manifest=manifest,
        )
        manager = _make_manager_with_registry(home_dir, registry)
        with pytest.raises((ManifestError, IntegrityError), match="undeclared"):
            manager.install("slm")

    def test_tarball_path_traversal_rejected(self, home_dir: Path):
        registry = FakeRegistry()
        # Build a tarball with an escaping member by hand.
        evil_payload = b"pwned"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../escape.py")
            info.size = len(evil_payload)
            tar.addfile(info, io.BytesIO(evil_payload))
        payload = buf.getvalue()
        manifest = json.dumps(
            {
                "name": "slm",
                "version": "1.0.0",
                "platform": "any",
                "python_tag": "cp311",
                # Manifest declares the traversal path with its real digest;
                # the installer must still reject extraction.
                "sha256": {"../escape.py": _sha256_bytes(evil_payload)},
                "enables": [],
            }
        )
        registry.releases[("slm", "1.0.0")] = {
            "manifest_json": manifest,
            "payload": payload,
            "asset_name": "slm-1.0.0-any-cp311.tar.gz",
            "tag": "v1.0.0",
        }
        manager = _make_manager_with_registry(home_dir, registry)
        # The manifest from_dict rejects traversal keys outright.
        with pytest.raises((ManifestError, IntegrityError)):
            manager.install("slm")


# ---------------------------------------------------------------------------
# list / info / remove
# ---------------------------------------------------------------------------


class TestListInfoRemove:
    def test_list_empty_returns_empty(self, manager: ExtensionManager):
        assert manager.list_installed() == []

    def test_list_returns_highest_version(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.registry.add_release("slm", "2.0.0", files={"a.py": b"2"})
        manager.install("slm", version="1.0.0")
        manager.install("slm", version="2.0.0")
        installed = manager.list_installed()
        assert len(installed) == 1
        assert installed[0].version == "2.0.0"

    def test_info_installed(self, manager: ExtensionManager):
        manager.registry.add_release(
            "slm", "1.0.0", files={"a.py": b"x"}, enables=("gliner",)
        )
        manager.install("slm")
        info = manager.info("slm")
        assert info["installed"] is True
        assert info["version"] == "1.0.0"
        assert "gliner" in info["enables"]

    def test_info_not_installed_first_party_hint(self, manager: ExtensionManager):
        manager.registry.search_index.append(
            {"name": "pdf", "description": "pdf parser", "enables": ["fitz"]}
        )
        info = manager.info("pdf")
        assert info["installed"] is False
        assert info["name"] == "pdf"

    def test_info_unknown_raises(self, manager: ExtensionManager):
        with pytest.raises(ExtensionNotFoundError):
            manager.info("nope")

    def test_remove_deletes_dir_and_appends_tombstone(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"x"})
        manager.install("slm")
        res = manager.remove("slm")
        assert res["removed_versions"] == ["1.0.0"]
        assert not (manager.extensions_dir / "slm").exists()
        tomb = manager.extensions_dir / ".removed.jsonl"
        assert tomb.is_file()
        lines = [json.loads(ln) for ln in tomb.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        assert lines[0]["name"] == "slm"
        assert lines[0]["versions"] == ["1.0.0"]

    def test_remove_unknown_raises(self, manager: ExtensionManager):
        with pytest.raises(ExtensionNotFoundError):
            manager.remove("ghost")


# ---------------------------------------------------------------------------
# Path-traversal name validation (ISSUE-0007 security fix)
#
# remove/info/payload_dir/installed_versions used to join a user-supplied
# ``name`` onto extensions_dir WITHOUT the isalnum() check that install()
# applies. ``remove("..")`` -> shutil.rmtree(~/.mnemosyne). These tests pin
# the guard at every public name entry point.
# ---------------------------------------------------------------------------


class TestNameValidation:
    @pytest.mark.parametrize(
        "evil_name",
        ["..", "../..", "../etc/passwd", "/etc/passwd", "a/b", "a\\b", " ", ""],
    )
    def test_remove_rejects_traversal_without_touching_fs(
        self, manager: ExtensionManager, home_dir: Path, evil_name: str
    ):
        marker = home_dir / "survivor.txt"
        marker.write_text("must survive")
        # The home parent must NOT be deleted even though remove("..")
        # would otherwise resolve to it.
        with pytest.raises(IntegrityError):
            manager.remove(evil_name)
        # Filesystem untouched: home still exists, marker intact.
        assert home_dir.is_dir()
        assert marker.read_text() == "must survive"
        # And critically: extensions_dir was never created (remove bails
        # before any filesystem work, so not even the parent dir appears).
        assert not manager.extensions_dir.exists()

    def test_remove_rejects_double_dot_parent(self, manager: ExtensionManager):
        with pytest.raises(IntegrityError):
            manager.remove("../..")

    @pytest.mark.parametrize(
        "evil_name", ["..", "../etc/passwd", "/etc/passwd", "a/b", ""]
    )
    def test_info_rejects_traversal(self, manager: ExtensionManager, evil_name: str):
        with pytest.raises(IntegrityError):
            manager.info(evil_name)

    def test_payload_dir_rejects_traversal(self, manager: ExtensionManager):
        with pytest.raises(IntegrityError):
            manager.payload_dir("../..", "1.0.0")

    @pytest.mark.parametrize(
        "evil_name", ["..", "../etc", "a/b"]
    )
    def test_installed_versions_rejects_traversal(
        self, manager: ExtensionManager, evil_name: str
    ):
        with pytest.raises(IntegrityError):
            manager.installed_versions(evil_name)

    def test_latest_installed_version_rejects_traversal(
        self, manager: ExtensionManager
    ):
        with pytest.raises(IntegrityError):
            manager.latest_installed_version("..")

    @pytest.mark.parametrize(
        "good_name", ["slm", "pdf", "my-ext", "my_ext", "Ext123", "a"]
    )
    def test_valid_names_accepted(
        self, manager: ExtensionManager, good_name: str
    ):
        # payload_dir must succeed for any valid name (no raise, sane path).
        p = manager.payload_dir(good_name, "1.0.0")
        assert p.name == "1.0.0"
        assert p.parent.name == good_name
        # installed_versions / info on a missing-but-valid name do NOT raise
        # IntegrityError (they return [] / ExtensionNotFoundError instead).
        assert manager.installed_versions(good_name) == []
        with pytest.raises(ExtensionNotFoundError):
            manager.info(good_name)

    def test_remove_does_not_call_rmtree_on_traversal(
        self, manager: ExtensionManager, monkeypatch: pytest.MonkeyPatch
    ):
        # Belt-and-braces: even if the validation somehow moved, rmtree must
        # never run for a traversal name.
        called: list[str] = []
        import mnemosyne.extensions.installer as inst_mod

        orig_rmtree = inst_mod.shutil.rmtree

        def spy_rmtree(path, *a, **kw):
            called.append(str(path))
            return orig_rmtree(path, *a, **kw)

        monkeypatch.setattr(inst_mod.shutil, "rmtree", spy_rmtree)
        with pytest.raises(IntegrityError):
            manager.remove("..")
        assert called == []


# ---------------------------------------------------------------------------
# upgrade / search
# ---------------------------------------------------------------------------


class TestUpgradeSearch:
    def test_upgrade_installs_newer_version(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        manager.registry.add_release("slm", "1.1.0", files={"a.py": b"2"})
        results = manager.upgrade(name="slm")
        assert results[0]["status"] == "upgraded"
        assert results[0]["from"] == "1.0.0"
        assert results[0]["to"] == "1.1.0"

    def test_upgrade_reports_up_to_date(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        results = manager.upgrade(name="slm")
        assert results[0]["status"] == "up-to-date"
        assert results[0]["version"] == "1.0.0"

    def test_upgrade_all_iterates_installed(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.registry.add_release("pdf", "1.0.0", files={"b.py": b"2"})
        manager.install("slm")
        manager.install("pdf")
        manager.registry.add_release("slm", "2.0.0", files={"a.py": b"3"})
        manager.registry.add_release("pdf", "2.0.0", files={"b.py": b"4"})
        results = manager.upgrade(all_=True)
        names_upgraded = {r["name"] for r in results if r["status"] == "upgraded"}
        assert names_upgraded == {"slm", "pdf"}

    def test_search_filters_by_query(self, manager: ExtensionManager):
        manager.registry.search_index = [
            {"name": "slm", "description": "semantic models", "enables": []},
            {"name": "pdf", "description": "pdf parsing", "enables": []},
        ]
        results = manager.search("pdf")
        assert len(results) == 1
        assert results[0]["name"] == "pdf"


# ---------------------------------------------------------------------------
# Runtime sys.path loader (REQ-PKG-003)
# ---------------------------------------------------------------------------


class TestLoader:
    def test_load_injects_highest_version_into_sys_path(
        self, home_dir: Path, manager: ExtensionManager
    ):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.registry.add_release("slm", "2.0.0", files={"a.py": b"2"})
        manager.install("slm", version="1.0.0")
        manager.install("slm", version="2.0.0")
        paths: list[str] = []
        added = load_installed_extensions(home=home_dir, paths=paths)
        assert len(added) == 1
        # Highest version (2.0.0) injected.
        expected = str(home_dir / "extensions" / "slm" / "2.0.0")
        assert added[0] == expected
        assert paths[0] == expected

    def test_load_excludes_removed_extensions(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        manager.remove("slm")
        paths: list[str] = []
        added = load_installed_extensions(home=manager.home, paths=paths)
        assert added == []

    def test_load_skips_corrupt_manifest(
        self, home_dir: Path, manager: ExtensionManager, capsys: pytest.CaptureFixture
    ):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        # Corrupt the on-disk manifest after install.
        (home_dir / "extensions" / "slm" / "1.0.0" / "manifest.json").write_text(
            "not json"
        )
        paths: list[str] = []
        added = load_installed_extensions(home=home_dir, paths=paths)
        assert added == []
        err = capsys.readouterr().err
        assert "skipping extension" in err

    def test_load_is_idempotent(self, manager: ExtensionManager):
        manager.registry.add_release("slm", "1.0.0", files={"a.py": b"1"})
        manager.install("slm")
        paths: list[str] = []
        load_installed_extensions(home=manager.home, paths=paths)
        added2 = load_installed_extensions(home=manager.home, paths=paths)
        assert added2 == []


# ---------------------------------------------------------------------------
# E2E: extension install slm via the CLI with a mocked payload
# ---------------------------------------------------------------------------


class TestCliE2E:
    def test_install_slm_e2e_via_cli(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        from mnemosyne.cli import main

        registry = FakeRegistry()
        registry.add_release(
            "slm",
            "1.0.0",
            files={"gliner/__init__.py": b"# gliner\n", "torch_stub.py": b"# torch\n"},
            enables=("gliner", "torch"),
        )
        monkeypatch.setenv("MNEMOSYNE_HOME", str(home_dir))
        monkeypatch.setattr(
            "mnemosyne.extensions.installer.HttpGithubRegistry",
            lambda *a, **kw: registry,
        )
        rc = main(["extension", "install", "slm"])
        assert rc in (0, None)  # main returns None on success
        out = capsys.readouterr().out
        assert "installed slm 1.0.0" in out
        # Payload landed on disk.
        assert (home_dir / "extensions" / "slm" / "1.0.0" / "manifest.json").is_file()

    def test_list_via_cli_after_install(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        from mnemosyne.cli import main

        registry = FakeRegistry()
        registry.add_release("slm", "1.0.0", files={"a.py": b"x"})
        monkeypatch.setenv("MNEMOSYNE_HOME", str(home_dir))
        monkeypatch.setattr(
            "mnemosyne.extensions.installer.HttpGithubRegistry",
            lambda *a, **kw: registry,
        )
        assert main(["extension", "install", "slm"]) in (0, None)
        capsys.readouterr()
        assert main(["extension", "list"]) in (0, None)
        out = capsys.readouterr().out
        assert "slm" in out and "1.0.0" in out

    def test_install_json_format(
        self, home_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        from mnemosyne.cli import main

        registry = FakeRegistry()
        registry.add_release("slm", "1.0.0", files={"a.py": b"x"})
        monkeypatch.setenv("MNEMOSYNE_HOME", str(home_dir))
        monkeypatch.setattr(
            "mnemosyne.extensions.installer.HttpGithubRegistry",
            lambda *a, **kw: registry,
        )
        assert main(["extension", "install", "slm", "--format", "json"]) in (0, None)
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload[0]["status"] == "installed"
        assert payload[0]["name"] == "slm"


# ---------------------------------------------------------------------------
# Manifest schema unit tests
# ---------------------------------------------------------------------------


class TestManifestSchema:
    def test_manifest_rejects_non_object_root(self):
        with pytest.raises(ManifestError):
            ExtensionManifest.from_dict([1, 2, 3])  # type: ignore[arg-type]

    def test_manifest_rejects_missing_name(self):
        with pytest.raises(ManifestError):
            ExtensionManifest.from_dict({"version": "1.0.0", "sha256": {}})

    def test_manifest_rejects_bad_sha_digest(self):
        with pytest.raises(ManifestError, match="64-hex"):
            ExtensionManifest.from_dict(
                {"name": "slm", "version": "1.0.0", "sha256": {"a.py": "xyz"}}
            )

    def test_manifest_round_trip(self):
        m = ExtensionManifest.from_dict(
            {
                "name": "slm",
                "version": "1.0.0",
                "sha256": {"a.py": "a" * 64},
                "enables": ["gliner"],
            }
        )
        d = m.to_dict()
        assert d["name"] == "slm"
        assert d["sha256"] == {"a.py": "a" * 64}

    def test_sha256_file_streams_large_file(self, tmp_path: Path):
        big = tmp_path / "big.bin"
        data = b"0" * (1 << 18)  # 256 KiB > default 64 KiB chunk
        big.write_bytes(data)
        digest = sha256_file(big)
        # Sanity: matches hashlib directly.
        import hashlib

        assert digest == hashlib.sha256(data).hexdigest()
