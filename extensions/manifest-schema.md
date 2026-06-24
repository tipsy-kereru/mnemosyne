# Extension manifest schema (REQ-PKG-010)

A `manifest.json` ships beside every extension payload tarball. It binds the
payload to a name/version/platform/python_tag and enumerates the SHA256 of
every file in the payload. The installer refuses to proceed on any mismatch
and rolls back so no partial install is left on disk.

## Canonical shape

```json
{
  "name": "slm",
  "version": "1.0.0",
  "platform": "linux-x86_64",
  "python_tag": "cp312",
  "sha256": {
    "gliner/__init__.py": "<64 hex chars>",
    "gliner/model.bin": "<64 hex chars>",
    "torch/__init__.py": "<64 hex chars>"
  },
  "enables": ["gliner", "torch"],
  "signer": "tipsy-kereru",
  "signature": "<optional detached signature; not verified by base install>"
}
```

## Fields

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `name` | yes | string | Extension identifier; must match the install request. |
| `version` | yes | string | Semver-ish (`1.0.0`, `v1.0.0`). Pre-release suffixes sort below release. |
| `platform` | no | string | `linux-x86_64`, `darwin-arm64`, `windows-x86_64`, or `any`. Defaults to `any`. |
| `python_tag` | no | string | `cp311`, `cp312`, `cp313`, etc. Defaults to `cp312`. |
| `sha256` | yes | object | Map of relative path -> 64-hex SHA256 digest. Must cover every file in the payload. |
| `enables` | no | array of strings | Feature flags this extension activates (e.g. `gliner`, `fitz`). |
| `signer` | no | string | Audit identity that produced the manifest. |
| `signature` | no | string | Detached signature blob. Not cryptographically verified by the base installer in this revision (cosign/sigstore land in PACKAGE-D). |

## Safety invariants (enforced by the installer)

1. **Every file verified.** Each file listed in `sha256` must exist with a
   matching digest. A missing file or digest mismatch aborts the install.
2. **No undeclared files.** Any file in the payload tarball not enumerated
   in `sha256` (except `manifest.json` itself) aborts the install.
3. **Path-traversal hardening.** Relative path keys must match
   `^[A-Za-z0-9_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+$` and must not contain `..`
   or be absolute. The tarball extraction separately refuses members that
   escape the payload directory or are devices/symlinks.
4. **Name binding.** `name` in the manifest must equal the requested
   extension name.
5. **Downgrade refusal.** Installing an older version over a newer one is
   rejected unless `--force` is passed.
6. **Rollback.** On any integrity failure the staging directory is removed
   and the per-name skeleton directory is cleaned up if empty, so a failed
   install leaves no trace on disk.

## How to regenerate

```bash
cd extensions/<name>
MNEMOSYNE_EXT_VERSION=1.0.0 ./build.sh
```

`build.sh` assembles the payload, computes per-file SHA256, and writes the
canonical `dist/manifest.json`.
