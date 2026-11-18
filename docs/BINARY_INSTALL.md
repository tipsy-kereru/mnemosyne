# Binary Installation

The `mnemosyne` CLI ships native release assets built with PyOxidizer on
Linux/macOS and a self-contained PyInstaller EXE on Windows, attached to each
[GitHub Release](https://github.com/tipsy-kereru/mnemosyne/releases).
This document covers install paths, platform support, the unsigned-macOS
workaround, the binary-size advisory, and deferred items.

## Quick start

### Linux + macOS (curl | sh)

```bash
curl -fsSL https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.sh | sh
```

- Installs to `~/.local/bin/mnemosyne` by default (override with
  `MNEMOSYNE_INSTALL_DIR`).
- Verifies the SHA256 of the binary and of its companion tarball against
  `SHA256SUMS.txt` before install; aborts on mismatch.
- Also unpacks the companion directories (`lib/`, `anyio/`, `referencing/`,
  `jsonschema_specifications/`) from `mnemosyne-<platform>.dist.tar.gz` next to
  the binary. The binary starts without them, but `mcp serve` fails with
  `No module named 'anyio'`.
- Refuses to overwrite an existing binary or companion directory unless
  `--force` / `MNEMOSYNE_FORCE=1`.

### Windows (PowerShell 5.1+)

```powershell
iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
```

- Installs to `%LOCALAPPDATA%\Programs\mnemosyne\mnemosyne.exe`.
- Prepends the install dir to the user `PATH` (open a new shell to pick it up).
- Same SHA256-verify + refuse-overwrite semantics.
- Windows 11 with Smart App Control blocks this unsigned EXE; see
  [Windows Smart App Control](#windows-smart-app-control).

## Platform matrix

| Platform            | Asset                          | Status      | Notes |
|---------------------|--------------------------------|-------------|-------|
| linux-x86_64        | `mnemosyne-linux-x86_64`       | GA          | Built natively on `ubuntu-latest`. |
| darwin-arm64        | `mnemosyne-darwin-arm64`       | GA          | Native on `macos-14`. Unsigned (see below). |
| windows-x86_64      | `mnemosyne-windows-x86_64.exe` | Supported   | Native Windows CI; CPython 3.11 + PyInstaller 6.22.2. No Python installation required. |
| darwin-x86_64       | —                              | not shipped | Removed from matrix (slow macos-13 build blocked release). Re-add when stable. |
| linux-aarch64       | —                              | not shipped | PyOxidizer cross-compile exec-format limitation. Needs native arm64 runner. |

The release supports **linux-x86_64, darwin-arm64 and windows-x86_64**.
All three builds must pass their runtime smoke checks before publication.
Linux arm64 and macOS x86_64 remain outside the supported release set.

## Windows build and runtime

Starting with **v0.12.1**, download `mnemosyne-windows-x86_64.exe` directly or
use the PowerShell installer above. The EXE contains CPython, the Rust core,
runtime DLLs, MCP SDK 1.x and package data; companion folders are not required.
Do not run the application as administrator. Its one-file loader extracts
runtime files to a temporary directory for the lifetime of the process.

The Windows CI smoke moves the EXE out of the build directory and removes
Python/toolchain directories from `PATH`. It exercises socket/TLS, SQLite FTS5,
Rust/MCP imports, A→B→A lifecycle updates, stale-job rejection and two wiki
publications. This catches DLL dependencies hidden by the build machine.

The former PyOxidizer Windows path is replaced, not shipped as an alternative.
Keyless cosign bundles verify release provenance but are **not Authenticode
signatures**: Windows SmartScreen may still report an unknown publisher, and
Smart App Control blocks the EXE outright (next section).

See [Windows build instructions](BINARY_BUILD.md#windows-x86_64).

## Windows Smart App Control

With **Smart App Control (SAC)** in enforcement mode, Windows 11 refuses to run
unsigned executables that have no cloud reputation. The release EXE is
unsigned (see Deferred items) and new, so it does not start: Windows reports
that an application control policy blocked the file and Code Integrity logs
event 3077 for it. SAC has no per-file exception, so SmartScreen's *More info →
Run anyway* does not apply.

Confirm the cause (read-only PowerShell, no administrator rights needed):

```powershell
(Get-MpComputerStatus).SmartAppControlState    # On = enforcement
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; Id=3077} -MaxEvents 5 |
  ForEach-Object { ([xml]$_.ToXml()).Event.EventData.Data | Where-Object Name -eq 'File Name' | ForEach-Object { $_.'#text' } }
```

### Workaround: run from a Python environment

The package itself is pure Python, so a normal install works with SAC on. The
MCP server and CLI behave the same as the EXE and use the same data directory
(`%USERPROFILE%\mnemosyne`).

```powershell
uv venv "$env:USERPROFILE\.venvs\mnemosyne" --python 3.12
uv pip install --python "$env:USERPROFILE\.venvs\mnemosyne\Scripts\python.exe" `
  "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne@v0.12.1"
& "$env:USERPROFILE\.venvs\mnemosyne\Scripts\mnemosyne.exe" --version
```

Point MCP clients at `%USERPROFILE%\.venvs\mnemosyne\Scripts\mnemosyne.exe` with
arguments `mcp serve`.

Verified on Windows 11 build 26300 with SAC `On`: `--version`, an MCP
`initialize` / `tools/list` / `mnemosyne_stats` round trip, `ingest extract` and
two consecutive `lifecycle rebuild` runs all succeeded with no new Code
Integrity block events.

Limits of this workaround:

- The dependencies' native extensions (`pydantic_core`, `rpds`, `pywin32`,
  SQLAlchemy and others) are unsigned too. SAC let them load because those
  wheels are widely used, so their reputation is known. A newer wheel can be
  blocked until it builds reputation. Record the working set with
  `uv pip freeze > mnemosyne-requirements.txt`, upgrade deliberately, and
  re-run `--version` and the MCP check afterwards.
- The interpreter must itself be allowed; the `uv`-managed CPython 3.12 was.
- The optional Rust core (`mnemosyne_core`) is not part of this install, so
  code extraction uses the regex fallback.

### Other options

- **WSL2:** run `mnemosyne` inside a Linux distribution and start MCP with
  `wsl.exe -d <distro> -e <path-to>/mnemosyne mcp serve`. Linux processes are
  not subject to Windows SAC. Keep the SQLite database on the Linux
  filesystem, not under `/mnt/c`.
- **Turn SAC off:** Windows Security → App & browser control → Smart App
  Control. This lowers protection for the whole machine, and re-enabling is not
  possible on every Windows build; read Microsoft's current SAC FAQ first.
- **Signed releases:** tracked under Deferred items.

## macOS unsigned-binary workaround (R-PKG-005)

macOS binaries are NOT notarized (no Apple Developer cert). On first run,
Gatekeeper may block the binary with `“mnemosyne” cannot be opened because the
developer cannot be verified.`

Fix: strip the quarantine attribute:

```bash
xattr -d com.apple.quarantine ~/.local/bin/mnemosyne
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
# Linux + macOS: INSTALL_DIR is ~/.local/bin unless MNEMOSYNE_INSTALL_DIR was set
d="${MNEMOSYNE_INSTALL_DIR:-$HOME/.local/bin}"
rm -f "$d/mnemosyne"
rm -rf "$d/lib" "$d/anyio" "$d/referencing" "$d/jsonschema_specifications"

# Windows (PowerShell), release EXE
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\mnemosyne"

# Windows (PowerShell), Python-environment workaround
Remove-Item -Recurse -Force "$env:USERPROFILE\.venvs\mnemosyne"
```

On Linux and macOS the installer unpacks `lib/`, `anyio/`, `referencing/` and
`jsonschema_specifications/` next to the binary; remove those four directories
too, and check first that they are not shared with another tool in the same
install directory. On Windows the release EXE is self-contained, so deleting
its folder is sufficient.

### pip package

```bash
pip uninstall mnemosyne-kg
```

This also covers editable (`pip install -e .`) installs — `pip` resolves both
to the same distribution name.

### Optional extensions (SLM / PDF) — not yet shipped

The sidecar extension registry repos (`mnemosyne-ext-slm`, `mnemosyne-ext-pdf`)
are **not published yet** (tracked in ISSUE-0011, follow-up release). Until then
there are no extensions to remove; SLM/PDF are obtained via the pip extras path.
When the payloads ship, the removal commands will be:

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
| Windows: "blocked by an application control policy", Code Integrity event 3077 | Smart App Control blocks the unsigned EXE | see [Windows Smart App Control](#windows-smart-app-control) |
| `ModuleNotFoundError: No module named 'anyio'` from `mcp serve` on Linux/macOS | installed with an older `install.sh` that copied only the binary | re-run the current `install.sh --force`, or unpack the release's `mnemosyne-<platform>.dist.tar.gz` next to the binary: `tar -xzf mnemosyne-<platform>.dist.tar.gz -C ~/.local/bin` |

## Deferred items (out of ISSUE-0009 scope)

- PyOxidizer 0.4x + CPython 3.12 upgrade (primary size-reduction lever).
- macOS notarization with Apple Developer cert (R-PKG-005).
- Windows arm64 (R-PKG-007, post-GA).
- Windows code-signing (signtool/Authenticode) — same cert-gating as macOS.
- Extension payload publication (slm/pdf) — belongs to PACKAGE-B follow-up.
