<#
.SYNOPSIS
    Agentry uninstaller for Windows.

.DESCRIPTION
    Cleanly removes everything `scripts/install.ps1` installed:

      - The Windows Service (if registered via `agentry service install`)
      - The agentry Python package
      - The npm globals: @anthropic-ai/claude-code and @openai/codex
      - The user data folder %USERPROFILE%\Agentry\
      - The legacy %USERPROFILE%\.agentry\ folder (if you have it from
        an earlier install)
      - Optionally: Node.js + NSSM (with -RemoveDeps; off by default
        because other tools may use them)

    Idempotent — safe to re-run; skips what's already absent.

    Does NOT touch your `claude login` / `codex login` OAuth credentials
    (those live in places owned by the CLIs themselves) — to fully
    sign out, run `claude logout` and `codex logout` separately.

.PARAMETER KeepConfig
    Keep %USERPROFILE%\Agentry\.env and pipeline.local.toml. Useful for
    reinstalling without losing your secrets / settings. State and logs
    are still removed.

.PARAMETER RemoveDeps
    Also winget-uninstall Node.js and NSSM. Off by default since other
    tools on your machine may depend on them.

.EXAMPLE
    # Standard uninstall — removes the service, the npm CLIs, and the user folder.
    # Leaves Node.js and NSSM in place.
    .\scripts\uninstall.ps1

.EXAMPLE
    # Reinstall later without losing your .env:
    .\scripts\uninstall.ps1 -KeepConfig

.EXAMPLE
    # Full removal including Node.js and NSSM.
    .\scripts\uninstall.ps1 -RemoveDeps
#>

[CmdletBinding()]
param(
    [switch]$KeepConfig = $false,
    [switch]$RemoveDeps = $false
)

$ErrorActionPreference = 'Continue'  # never abort the whole uninstall on one failed step

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Test-Command($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# -----------------------------------------------------------------------------
# 1. Stop and remove the Windows Service (if present)
# -----------------------------------------------------------------------------

Write-Step "Removing agentry Windows Service (if installed)"

if (Test-Command 'nssm') {
    $svcStatus = & nssm status agentry 2>&1
    if ($svcStatus -notmatch 'service .* not found') {
        & nssm stop agentry 2>$null
        & nssm remove agentry confirm 2>$null
        Write-OK "removed agentry NSSM service"
    } else {
        Write-Skip "no agentry service registered"
    }
} else {
    Write-Skip "nssm not on PATH; skipping service removal"
}

# Belt-and-braces: also use sc.exe in case nssm isn't reachable but the
# service entry is still in SCM somehow.
$scResult = & sc.exe query agentry 2>&1
if ($scResult -notmatch 'does not exist') {
    & sc.exe stop agentry 2>$null | Out-Null
    & sc.exe delete agentry 2>$null | Out-Null
}

# -----------------------------------------------------------------------------
# 2. Uninstall agentry Python package
# -----------------------------------------------------------------------------

Write-Step "Uninstalling agentry Python package"

$python = if (Test-Command 'python') { 'python' } elseif (Test-Command 'py') { 'py' } else { $null }
if ($python) {
    & $python -m pip uninstall -y agentry 2>&1 | Out-Null
    Write-OK "agentry uninstalled (or was already absent)"
} else {
    Write-Warn "no python on PATH — skipping pip uninstall"
}

# -----------------------------------------------------------------------------
# 3. Uninstall the LLM CLIs (npm globals)
# -----------------------------------------------------------------------------

Write-Step "Removing npm globals (claude-code + codex)"

if (Test-Command 'npm') {
    & npm uninstall -g '@anthropic-ai/claude-code' 2>&1 | Out-Null
    Write-OK "removed @anthropic-ai/claude-code"
    & npm uninstall -g '@openai/codex' 2>&1 | Out-Null
    Write-OK "removed @openai/codex"
} else {
    Write-Skip "npm not on PATH"
}

# -----------------------------------------------------------------------------
# 4. Remove the user data folder
# -----------------------------------------------------------------------------

$ag = Join-Path $env:USERPROFILE 'Agentry'
$ag_legacy = Join-Path $env:USERPROFILE '.agentry'

Write-Step "Cleaning up user data folder"

if ($KeepConfig) {
    # Preserve .env and pipeline.local.toml; remove only state/logs.
    foreach ($sub in @('state', 'logs', 'workspaces')) {
        $p = Join-Path $ag $sub
        if (Test-Path $p) {
            Remove-Item -Recurse -Force $p
            Write-OK "removed $p"
        }
    }
    Write-OK "kept $ag\.env and $ag\pipeline.local.toml (-KeepConfig)"
    if (Test-Path $ag_legacy) {
        Write-Warn "legacy $ag_legacy still present; remove manually if not in use"
    }
} else {
    foreach ($d in @($ag, $ag_legacy)) {
        if (Test-Path $d) {
            Remove-Item -Recurse -Force $d
            Write-OK "removed $d"
        } else {
            Write-Skip "$d not present"
        }
    }
}

# -----------------------------------------------------------------------------
# 5. Optionally remove Node.js + NSSM (-RemoveDeps)
# -----------------------------------------------------------------------------

if ($RemoveDeps) {
    Write-Step "Removing Node.js (-RemoveDeps)"
    if (Test-Command 'winget') {
        & winget uninstall --id OpenJS.NodeJS.LTS --silent --accept-source-agreements 2>&1 | Out-Null
        Write-OK "Node.js removed (or was already absent)"
        & winget uninstall --id NSSM.NSSM --silent --accept-source-agreements 2>&1 | Out-Null
        Write-OK "NSSM removed (or was already absent)"
    } else {
        Write-Warn "winget not present; uninstall Node.js and NSSM manually"
    }
} else {
    Write-Skip "Keeping Node.js + NSSM (use -RemoveDeps to remove)"
}

# -----------------------------------------------------------------------------
# 6. PATH cleanup (only the entries we added)
# -----------------------------------------------------------------------------

Write-Step "Cleaning up user PATH entries"

$npmDir = Join-Path $env:APPDATA 'npm'
if (-not $RemoveDeps) {
    Write-Skip "leaving $npmDir on PATH (other npm tools may need it; pass -RemoveDeps to remove)"
} else {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $entries = $userPath -split ';' | Where-Object { $_ -ne '' -and $_ -ne $npmDir }
    [Environment]::SetEnvironmentVariable("Path", ($entries -join ';'), "User")
    Write-OK "removed $npmDir from user PATH"
}

# -----------------------------------------------------------------------------
# 7. Summary
# -----------------------------------------------------------------------------

Write-Host "`n=== Uninstall complete ===" -ForegroundColor Green

if (-not $KeepConfig) {
    Write-Host @"

What was removed:
  - The agentry Windows Service (if registered)
  - The agentry Python package
  - The npm globals @anthropic-ai/claude-code and @openai/codex
  - $ag (your user data folder)
  - $ag_legacy (legacy folder from old installs, if present)
"@ -ForegroundColor Cyan
} else {
    Write-Host @"

What was removed:
  - The agentry Windows Service
  - The agentry Python package
  - The npm globals @anthropic-ai/claude-code and @openai/codex
  - $ag\state, $ag\logs, $ag\workspaces

What was KEPT (per -KeepConfig):
  - $ag\.env
  - $ag\pipeline.local.toml
"@ -ForegroundColor Cyan
}

if (-not $RemoveDeps) {
    Write-Host @"

What was kept (use -RemoveDeps to also remove these):
  - Node.js
  - NSSM
  - $npmDir on user PATH

To fully sign out of the LLM subscriptions:
  - claude logout
  - codex logout
  (these manage credentials in their own locations, not in $ag)
"@ -ForegroundColor Cyan
}
