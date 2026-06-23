# mnemosyne extensions -- first-party build recipes (ISSUE-0007 / SPEC-PACKAGE-001 PACKAGE-B)

This directory holds **build recipes** for the first-party mnemosyne
extensions. It does NOT ship binary wheels (those are too large for git and
are platform/python-tag specific). Each subdirectory has a `build.sh` that
assembles a release tarball + signed `manifest.json` consumable by
`mnemosyne extension install`.

## Layout

```
extensions/
├── README.md              this file
├── manifest-schema.md     canonical manifest.json schema (REQ-PKG-010)
├── slm/
│   └── build.sh           GLiNER2 + REBEL + CPU torch payload builder
└── pdf/
    └── build.sh           pymupdf (fitz) payload builder
```

## Workflow

A maintainer runs, e.g.:

```bash
cd extensions/slm
MNEMOSYNE_EXT_VERSION=1.0.0 ./build.sh
# produces:
#   dist/slm-1.0.0-<platform>-<python_tag>.tar.gz
#   dist/manifest.json
```

The `dist/manifest.json` and the tarball are then attached to a GitHub
Release on `tipsy-kereru/mnemosyne-ext-slm`. Users install with:

```bash
mnemosyne extension install slm
```

The installer downloads the manifest + platform-matched tarball, verifies
every file's SHA256 against the manifest, and refuses on mismatch (with
rollback so no partial install is left on disk).

## What is NOT shipped here

- Binary wheels (torch, gliner, pymupdf) -- fetched by `build.sh` from PyPI
  at build time, never committed.
- The signed manifest itself -- `build.sh` generates it; the `signer` field
  records the human/machine that produced it. Detached cryptographic
  signatures (cosign/sigstore) land in PACKAGE-D; the base installer records
  `signer` for audit but SHA256-per-file is the load-bearing guarantee here.

## Adversarial guarantees

See `tests/test_extensions.py::TestIntegrity` for the rejection paths:
SHA mismatch, missing file, undeclared file, manifest tamper, downgrade
refusal, tarball path traversal. All abort with rollback.
