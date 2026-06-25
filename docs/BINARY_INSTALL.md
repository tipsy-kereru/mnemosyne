# Binary Installation

The `mnemosyne` CLI ships as a single PyOxidizer-built binary per platform,
attached to each [GitHub Release](https://github.com/tipsy-kereru/mnemosyne/releases).
This document covers install paths, platform support, the unsigned-macOS
workaround, the binary-size advisory, and deferred items.

## Quick start

### Linux + macOS (curl | sh)

```bash
curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh
```

- Installs to `/usr/local/bin/mnemosyne` by default (override with
  `MNEMOSYNE_INSTALL_DIR=$HOME/bin`).
- Verifies the SHA256 against `SHA256SUMS.txt` before install; aborts on
  mismatch.
- Refuses to overwrite an existing install unless `--force` /
  `MNEMOSYNE_FORCE=1`.

### Windows (PowerShell 5.1+)

```powershell
iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
```

- Installs to `%LOCALAPPDATA%\Programs\mnemosyne\mnemosyne.exe`.
- Prepends the install dir to the user `PATH` (open a new shell to pick it up).
- Same SHA256-verify + refuse-overwrite semantics.

## Platform matrix

| Platform            | Asset                          | Status     | Notes |
|---------------------|--------------------------------|------------|-------|
| linux-x86_64        | `mnemosyne-linux-x86_64`       | GA         | Built natively on `ubuntu-latest`. |
| darwin-arm64        | `mnemosyne-darwin-arm64`       | GA         | Native on `macos-14`. Unsigned (see below). |
| windows-x86_64      | `mnemosyne-windows-x86_64.exe` | GA         | Native on `windows-latest`. Unsigned. |
| darwin-x86_64       | `mnemosyne-darwin-x86_64`      | best-effort| Native on `macos-13`. Fast-follow if runner churn. |
| linux-aarch64       | `mnemosyne-linux-aarch64`      | best-effort| Cross-compiled from `ubuntu-latest`. Fast-follow if cross toolchain breaks. |

The pragmatic floor (AC2): linux-x86_64 + darwin-arm64 + windows-x86_64 MUST
succeed on every release; the other two are allowed to land as follow-ups if
a runner or cross-compile issue surfaces.

## macOS unsigned-binary workaround (R-PKG-005)

macOS binaries are NOT notarized (no Apple Developer cert). On first run,
Gatekeeper may block the binary with `“mnemosyne” cannot be opened because the
developer cannot be verified.`

Fix: strip the quarantine attribute:

```bash
xattr -d com.apple.quarantine /usr/local/bin/mnemosyne
```

`install.sh` prints this reminder at the end of a darwin install. The path to
notarized binaries is tracked in R-PKG-005 (gated on a codesign identity).

## Verifying signatures (cosign)

Linux + darwin binaries are signed with cosign keyless (sigstore) on tag
pushes. Signatures are uploaded as `<asset>.sigstore` next to each binary.

Verify after download:

```bash
cosign verify-blob \
  --certificate-identity-regexp 'https://github.com/tipsy-kereru/mnemosyne/.github/.+' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  --signature mnemosyne-linux-x86_64.sigstore \
  --bundle mnemosyne-linux-x86_64.sigstore \
  mnemosyne-linux-x86_64
```

Windows is unsigned for now (signtool/Authenticode deferred — same cert-gating
as macOS). If a cosign step transiently fails, the release upload is NOT
rolled back (signing has `continue-on-error: true`); re-check `.sigstore`
presence post-release.

## Binary-size advisory

The linux-x86_64 binary distribution lands around **145.8 MB** (binary +
`lib/` extension modules + filesystem-shipped `jsonschema_specifications` /
`referencing` companion dirs). This is above the 100 MB target in
SPEC-PACKAGE-001 §AC6.

The lever for the size reduction is the **PyOxidizer 0.4x + CPython 3.12
upgrade**, tracked as a follow-up to ISSUE-0008 / ISSUE-0009. The 0.2x → 0.3x
line renamed `PythonExecutable` builder methods and changed the
resource-visitor API; the two are NOT drop-in compatible, and revalidating
the AC2 `import mnemosyne_core` POC on 0.4x + 3.12 is a POC-grade effort
that was explicitly deferred to keep the cross-platform pipeline shippable.

The size is reported per build but NOT gated in CI; the binary works
(860-test suite green, `mnemosyne --help` + `mcp serve` smoke per platform).

## Man pages

`docs/man/*.1` are regenerated on each release via `scripts/gen_manpages.py`
and uploaded as `man-pages-<tag>.tar.gz` in the GitHub Release. Extract to
`/usr/local/share/man/man1/`:

```bash
tar -xzf man-pages-v0.1.0.tar.gz -C /usr/local/share/man
man mnemosyne-ingest-add
```

## Uninstall

There is no single uninstall script. Remove each install artifact manually in
any order — the binary, the pip package, the optional extensions, the agent
skill, and (optionally) the data directory.

### Binary

```bash
# Linux + macOS (default install path)
sudo rm -f /usr/local/bin/mnemosyne

# Linux + macOS (custom MNEMOSYNE_INSTALL_DIR)
rm -f "${MNEMOSYNE_INSTALL_DIR:-/usr/local/bin}/mnemosyne"

# Windows (PowerShell)
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\mnemosyne"
```

The binary ships next to a `lib/` directory and filesystem-shipped companion
packages (`jsonschema_specifications`, `referencing`). On Windows the whole
`mnemosyne\` folder is removed by the `Remove-Item -Recurse` above; on Linux
and macOS the companions are embedded resources inside the single binary, so
deleting the binary is sufficient.

### pip package

```bash
pip uninstall mnemosyne-kg
```

This also covers editable (`pip install -e .`) installs — `pip` resolves both
to the same distribution name.

### Optional extensions (SLM / PDF)

```bash
# Remove one extension at a time
mnemosyne extension list                # see what is installed
mnemosyne extension remove slm
mnemosyne extension remove pdf

# Or remove every extension at once
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}/extensions"
```

### Agent skill

```bash
# Claude Code default
rm -rf ~/.claude/skills/mnemosyne

# Generic agent frameworks
rm -rf ~/.agents/skills/mnemosyne

# Custom --path passed to `mnemosyne skill install`
rm -rf <your-custom-path>/mnemosyne
```

### Data directory (optional — preserves your knowledge graph)

The data directory holds `graph/knowledge.db`, `raw/`, and `wiki/`. **Keep it
if you want to reinstall later and continue from the same knowledge base.**
Remove it only for a fully clean slate:

```bash
rm -rf "${MNEMOSYNE_HOME:-$HOME/.mnemosyne}"
```

### Environment variables

Strip any of these you set in your shell rc (`~/.zshrc`, `~/.bashrc`,
PowerShell profile):

- `MNEMOSYNE_HOME`
- `MNEMOSYNE_LOCK_DIR`
- `MNEMOSYNE_CHAT_RETENTION_DAYS`
- `MNEMOSYNE_LLM_MAX_TOKENS`
- `MNEMOSYNE_INSTALL_DIR`
- `MNEMOSYNE_FORCE`

### Verify

```bash
which mnemosyne                # should print nothing
mnemosyne --version            # should report "command not found"
ls ~/.mnemosyne 2>/dev/null    # should print nothing if data dir removed
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `install.sh: ERROR: /usr/local/bin is not writable` | non-root, dir owned by root | `sudo sh install.sh`, or `MNEMOSYNE_INSTALL_DIR=$HOME/bin sh` |
| `checksum mismatch for mnemosyne-...` | partial download / proxy corruption | re-run install; check `curl -I` of the asset URL |
| `mnemosyne: command not found` after Windows install | PATH not refreshed | open a new PowerShell window |
| macOS Gatekeeper blocks binary | unsigned (R-PKG-005) | `xattr -d com.apple.quarantine <path>` |
| `No module named 'referencing._cores'` at boot | FILESYSTEM_PACKAGES missing from install dir | re-run install; do not move the binary without the companion dirs |

## Deferred items (out of ISSUE-0009 scope)

- PyOxidizer 0.4x + CPython 3.12 upgrade (primary size-reduction lever).
- macOS notarization with Apple Developer cert (R-PKG-005).
- Windows arm64 (R-PKG-007, post-GA).
- Windows code-signing (signtool/Authenticode) — same cert-gating as macOS.
- Extension payload publication (slm/pdf) — belongs to PACKAGE-B follow-up.
