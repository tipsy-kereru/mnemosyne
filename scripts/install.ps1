# install.ps1 — fetch + verify + install the mnemosyne binary on Windows.
#
# SPEC: SPEC-PACKAGE-001 (PACKAGE-D, REQ-PKG-009)
# Issue: ISSUE-0009
#
# Usage (from PowerShell 5.1+):
#   iwr https://github.com/tipsy-kereru/mnemosyne/releases/latest/download/install.ps1 -UseBasicParsing | iex
#
# Environment:
#   $env:MNEMOSYNE_INSTALL_DIR  Override install dir (default: %LOCALAPPDATA%\Programs\mnemosyne)
#   $env:MNEMOSYNE_FORCE        "1" to overwrite an existing install.
#
# Behavior:
#   1. Verify windows-x86_64 (arm64 deferred — R-PKG-007).
#   2. Fetch mnemosyne-windows-x86_64.exe + SHA256SUMS.txt from the latest release.
#   3. Verify SHA256 via Get-FileHash; abort on mismatch.
#   4. Install to ${InstallDir}\mnemosyne.exe; prepend install dir to user PATH.
#   5. Refuse overwrite unless -Force / $env:MNEMOSYNE_FORCE=1.
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$Repo = 'tipsy-kereru/mnemosyne'
$BaseUrl = "https://github.com/$Repo/releases/latest/download"

if ($env:MNEMOSYNE_FORCE -eq '1') { $Force = $true }

if (-not $env:LOCALAPPDATA) {
    $env:LOCALAPPDATA = Join-Path $env:USERPROFILE 'AppData\Local'
}
$InstallDir = if ($env:MNEMOSYNE_INSTALL_DIR) {
    $env:MNEMOSYNE_INSTALL_DIR
} else {
    Join-Path $env:LOCALAPPDATA 'Programs\mnemosyne'
}

function Write-Info($msg) { Write-Host "install.ps1: $msg" }
function Write-Err($msg)  { Write-Host "install.ps1: ERROR: $msg" -ForegroundColor Red }

# ---- platform check ---------------------------------------------------------
$OsArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
if ($OsArch -ne 'X64') {
    Write-Err "unsupported windows arch: $OsArch (windows-x86_64 only; arm64 deferred per R-PKG-007)"
    exit 1
}

$Asset = 'mnemosyne-windows-x86_64.exe'
$BinPath = Join-Path $InstallDir 'mnemosyne.exe'

Write-Info "detected platform: windows-x86_64"
Write-Info "install dir: $InstallDir"

if ((Test-Path $BinPath) -and -not $Force) {
    Write-Err "refusing to overwrite existing $BinPath (pass -Force or set `$env:MNEMOSYNE_FORCE=1)"
    exit 1
}

$TmpDir = Join-Path $env:TEMP "mnemosyne-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null
try {
    $BinTmp = Join-Path $TmpDir $Asset
    $SumsTmp = Join-Path $TmpDir 'SHA256SUMS.txt'

    Write-Info "fetching $Asset + SHA256SUMS.txt"
    try {
        Invoke-WebRequest -Uri "$BaseUrl/$Asset" -OutFile $BinTmp -UseBasicParsing
    } catch {
        Write-Err "download failed for ${Asset}: $_"
        exit 1
    }
    try {
        Invoke-WebRequest -Uri "$BaseUrl/SHA256SUMS.txt" -OutFile $SumsTmp -UseBasicParsing
    } catch {
        Write-Err "download failed for SHA256SUMS.txt: $_"
        exit 1
    }

    # Parse "<sha256>  <asset>" from SHA256SUMS.txt.
    $Sums = Get-Content $SumsTmp
    $Expected = ($Sums | Where-Object { $_ -match "\s+mnemosyne-windows-x86_64\.exe\s*$" } |
        ForEach-Object { ($_ -split '\s+')[0] } | Select-Object -First 1)
    if (-not $Expected) {
        Write-Err "no checksum entry for $Asset in SHA256SUMS.txt"
        exit 1
    }

    $Actual = (Get-FileHash -Algorithm SHA256 -Path $BinTmp).Hash.ToLower()
    if ($Actual -ne $Expected.ToLower()) {
        Write-Err "checksum mismatch for $Asset"
        Write-Err "  expected: $Expected"
        Write-Err "  actual:   $Actual"
        exit 1
    }
    Write-Info "checksum OK ($Expected)"

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    Move-Item -Path $BinTmp -Destination $BinPath -Force
    Write-Info "installed: $BinPath"

    # Prepend install dir to user PATH (idempotent — no duplicate entries).
    $UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($UserPath -notlike "*$InstallDir*") {
        $NewPath = "$InstallDir;$UserPath"
        [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
        Write-Info "prepended $InstallDir to user PATH (open a new shell to update current session)"
    }

    Write-Info "next steps (new shell):"
    Write-Info "  mnemosyne --help"
    Write-Info "  mnemosyne extension install slm   # add the SLM payload"
}
finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
