<#
.SYNOPSIS
    Agentry — install machine-wide dependencies (Windows).

.DESCRIPTION
    Installs ONLY the things that need to live on your machine:
      - Python 3.11+
      - Node.js LTS
      - Claude Code CLI (npm install -g @anthropic-ai/claude-code)
      - OpenAI Codex CLI (npm install -g @openai/codex)

    Does NOT install agentry itself — agentry gets pip-installed into a
    local venv inside each target repo by `agentry/start.ps1`. This script
    is the one-time-per-machine setup; `add-to-target.ps1` is the
    one-time-per-repo setup.

    Idempotent. Safe to re-run.

.EXAMPLE
    iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.ps1 | iex
#>

[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    [ERR] $msg" -ForegroundColor Red }
function Test-Command($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Ensure-NpmGlobalPath {
    $npmDir = Join-Path $env:APPDATA 'npm'
    if (-not (Test-Path $npmDir)) { New-Item -ItemType Directory -Path $npmDir -Force | Out-Null }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$npmDir*") {
        [Environment]::SetEnvironmentVariable(
            "Path", ($userPath.TrimEnd(';') + ";$npmDir").TrimStart(';'), "User"
        )
        Write-OK "added $npmDir to user PATH"
    }
    if ($env:Path -notlike "*$npmDir*") { $env:Path = "$($env:Path);$npmDir" }
}

function Broadcast-EnvChange {
    $sig = @'
using System;
using System.Runtime.InteropServices;
public static class EnvRefresh {
  [DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
  static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam, uint flags, uint timeout, out IntPtr result);
  public static void Broadcast() {
    IntPtr r;
    SendMessageTimeout((IntPtr)0xffff, 0x001A, IntPtr.Zero, "Environment", 0x0002, 5000, out r);
  }
}
'@
    try { Add-Type -TypeDefinition $sig -Language CSharp -ErrorAction SilentlyContinue; [EnvRefresh]::Broadcast() } catch {}
}

# -----------------------------------------------------------------------------

Write-Step "Prerequisite checks"

if (-not (Test-Command 'winget')) {
    Write-Err "winget not found. Install 'App Installer' from the Microsoft Store first."
    exit 1
}
Write-OK "winget present"

# -----------------------------------------------------------------------------
# Python 3.11+
# -----------------------------------------------------------------------------

Write-Step "Python 3.11+"

$haveGoodPython = $false
foreach ($cmd in @('py -3', 'python', 'python3')) {
    try {
        $ver = & cmd /c "$cmd --version 2>&1"
        if ($LASTEXITCODE -eq 0 -and $ver -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]; $minor = [int]$matches[2]
            if (($major -gt 3) -or ($major -eq 3 -and $minor -ge 11)) {
                Write-OK "$cmd -> $ver"; $haveGoodPython = $true; break
            }
        }
    } catch {}
}

if (-not $haveGoodPython -or $Force) {
    winget install --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    Write-OK "Python installed"
} else {
    Write-Skip "Python 3.11+ already present"
}

# -----------------------------------------------------------------------------
# Node.js LTS
# -----------------------------------------------------------------------------

Write-Step "Node.js LTS"

if ((Test-Command 'node') -and -not $Force) {
    Write-Skip "Node.js already present ($(& node --version))"
} else {
    winget install --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Test-Command 'node')) {
        Write-Err "Node.js install completed but 'node' still not on PATH. Open a new shell and re-run."
        exit 1
    }
    Write-OK "Node.js installed: $(& node --version)"
}

Ensure-NpmGlobalPath

# -----------------------------------------------------------------------------
# LLM CLIs
# -----------------------------------------------------------------------------

Write-Step "Claude Code CLI"
if ((Test-Command 'claude') -and -not $Force) {
    Write-Skip "claude already on PATH"
} else {
    & npm install -g '@anthropic-ai/claude-code'
    if ($LASTEXITCODE -ne 0) { Write-Err "npm install -g @anthropic-ai/claude-code failed."; exit 1 }
    Refresh-Path
    Write-OK "Claude Code installed"
}

Write-Step "OpenAI Codex CLI"
if ((Test-Command 'codex') -and -not $Force) {
    Write-Skip "codex already on PATH"
} else {
    & npm install -g '@openai/codex'
    if ($LASTEXITCODE -ne 0) { Write-Err "npm install -g @openai/codex failed."; exit 1 }
    Refresh-Path
    Write-OK "Codex CLI installed"
}

Broadcast-EnvChange

# -----------------------------------------------------------------------------
# Verify
# -----------------------------------------------------------------------------

Write-Step "Verifying"
$ok = $true
foreach ($cmd in @('python', 'node', 'npm', 'claude', 'codex')) {
    if (Test-Command $cmd) {
        Write-OK "$cmd on PATH"
    } else {
        Write-Warn "$cmd NOT on PATH (open a new shell)"
        $ok = $false
    }
}

# -----------------------------------------------------------------------------

Write-Host @"

==> Done with machine setup.

Next:

  1. Authenticate the LLM CLIs (each opens your browser):

         claude login
         codex login

  2. Add agentry to a target repo. From inside that repo:

         iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex

  3. Configure or inspect the target without starting agents:

         .\agentry\start.ps1 gui --target .

     Then start agents only when you want them active:

         .\agentry\start.ps1

If 'claude' / 'codex' weren't on PATH above, open a new shell first.

"@ -ForegroundColor Cyan
