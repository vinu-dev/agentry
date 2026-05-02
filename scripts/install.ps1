<#
.SYNOPSIS
    Agentry one-shot installer for Windows.

.DESCRIPTION
    Installs everything Agentry needs on a Windows host:
      - Python 3.11+ (via winget, only if missing)
      - Node.js LTS (via winget, only if missing) — needed for `claude` and `codex` CLIs
      - agentry itself (pip from public GitHub)
      - Claude Code CLI (npm install -g @anthropic-ai/claude-code)
      - OpenAI Codex CLI (npm install -g @openai/codex)
      - NSSM (via winget) — only needed if you'll run agentry as a Windows Service
      - ~/.agentry/ directory with template .env and pipeline.local.toml

    The script does NOT do anything that requires your credentials:
      - It will NOT run `claude login` / `codex login` (OAuth needs your browser)
      - It will NOT fill in API keys / Discord webhook / GitHub PAT in your .env
    Those are clearly listed at the end as your remaining steps.

    Idempotent — safe to re-run. Skips installs that are already present.

.EXAMPLE
    # One-liner from the public repo:
    iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install.ps1 | iex

.EXAMPLE
    # Or from a clone:
    .\scripts\install.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipNssm = $false,        # NSSM only needed for `agentry service install`
    [switch]$Force                      # re-install everything even if present
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    [ERR] $msg" -ForegroundColor Red }

function Test-Command($cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    # Re-read both Machine and User PATH so newly-installed tools are found
    # without forcing a shell restart.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Ensure-NpmGlobalPath {
    $npmDir = Join-Path $env:APPDATA 'npm'
    if (-not (Test-Path $npmDir)) {
        New-Item -ItemType Directory -Path $npmDir -Force | Out-Null
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$npmDir*") {
        $userPath = ($userPath.TrimEnd(';') + ";$npmDir").TrimStart(';')
        [Environment]::SetEnvironmentVariable("Path", $userPath, "User")
        Write-OK "added $npmDir to user PATH"
    } else {
        Write-Skip "$npmDir already on user PATH"
    }
    if ($env:Path -notlike "*$npmDir*") {
        $env:Path = "$($env:Path);$npmDir"
    }
}

function Broadcast-EnvChange {
    # Tell Explorer + already-running processes that PATH changed so future
    # cmd/powershell windows they spawn pick up the new value automatically.
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
    try {
        Add-Type -TypeDefinition $sig -Language CSharp -ErrorAction SilentlyContinue
        [EnvRefresh]::Broadcast()
    } catch {
        # Best-effort; not fatal.
    }
}

# -----------------------------------------------------------------------------
# 1. Prerequisite checks
# -----------------------------------------------------------------------------

Write-Step "Checking prerequisites"

if (-not (Test-Command 'winget')) {
    Write-Err "winget not found. Install 'App Installer' from the Microsoft Store first, then re-run."
    exit 1
}
Write-OK "winget present"

# -----------------------------------------------------------------------------
# 2. Python 3.11+ (only install if missing)
# -----------------------------------------------------------------------------

Write-Step "Checking for Python 3.11+"

$haveGoodPython = $false
foreach ($cmd in @('py -3', 'python', 'python3')) {
    try {
        $ver = & cmd /c "$cmd --version 2>&1"
        if ($LASTEXITCODE -eq 0 -and $ver -match 'Python (\d+)\.(\d+)') {
            $major = [int]$matches[1]; $minor = [int]$matches[2]
            if (($major -gt 3) -or ($major -eq 3 -and $minor -ge 11)) {
                Write-OK "$cmd -> $ver"
                $haveGoodPython = $true
                break
            }
        }
    } catch {}
}

if (-not $haveGoodPython -or $Force) {
    Write-Host "    Installing Python 3.12 via winget..."
    winget install --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    Write-OK "Python installed"
} else {
    Write-Skip "Python 3.11+ already present"
}

# -----------------------------------------------------------------------------
# 3. Node.js LTS (only install if missing)
# -----------------------------------------------------------------------------

Write-Step "Checking for Node.js"

if ((Test-Command 'node') -and -not $Force) {
    $nodeVer = & node --version
    Write-Skip "Node.js already present ($nodeVer)"
} else {
    Write-Host "    Installing Node.js LTS via winget..."
    winget install --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Test-Command 'node')) {
        Write-Err "Node.js install completed but 'node' still not on PATH. Try opening a new shell and re-running."
        exit 1
    }
    Write-OK "Node.js installed: $(& node --version)"
}

# Make sure %APPDATA%\npm is on the persistent user PATH so claude/codex are
# reachable from cmd, PowerShell, and the eventual Windows Service.
Ensure-NpmGlobalPath

# -----------------------------------------------------------------------------
# 4. agentry (pip install from public GitHub)
# -----------------------------------------------------------------------------

Write-Step "Installing agentry (Python package)"

$pythonCmd = 'python'
if (-not (Test-Command 'python')) { $pythonCmd = 'py' }

if ((Test-Command 'agentry') -and -not $Force) {
    $agentryVer = & agentry --version
    Write-Skip "agentry already installed: $agentryVer"
} else {
    & $pythonCmd -m pip install --upgrade --user 'git+https://github.com/vinu-dev/agentry.git'
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed."
        exit 1
    }
    Refresh-Path
    if (-not (Test-Command 'agentry')) {
        Write-Warn "agentry installed but not on PATH yet. You may need to add the Python user-scripts dir to PATH. Try restarting your shell."
    } else {
        Write-OK "agentry installed: $(& agentry --version)"
    }
}

# -----------------------------------------------------------------------------
# 5. LLM CLIs (Claude Code + Codex)
# -----------------------------------------------------------------------------

Write-Step "Installing Claude Code CLI"
if ((Test-Command 'claude') -and -not $Force) {
    Write-Skip "claude already on PATH: $(& claude --version 2>&1 | Select-Object -First 1)"
} else {
    & npm install -g '@anthropic-ai/claude-code'
    if ($LASTEXITCODE -ne 0) {
        Write-Err "npm install -g @anthropic-ai/claude-code failed."
        exit 1
    }
    Refresh-Path
    Write-OK "Claude Code installed"
}

Write-Step "Installing OpenAI Codex CLI"
if ((Test-Command 'codex') -and -not $Force) {
    Write-Skip "codex already on PATH: $(& codex --version 2>&1 | Select-Object -First 1)"
} else {
    & npm install -g '@openai/codex'
    if ($LASTEXITCODE -ne 0) {
        Write-Err "npm install -g @openai/codex failed."
        exit 1
    }
    Refresh-Path
    Write-OK "Codex CLI installed"
}

# -----------------------------------------------------------------------------
# 6. NSSM (only if user wants service install)
# -----------------------------------------------------------------------------

if (-not $SkipNssm) {
    Write-Step "Installing NSSM (for `agentry service install`)"
    if ((Test-Command 'nssm') -and -not $Force) {
        Write-Skip "nssm already present"
    } else {
        winget install --id NSSM.NSSM --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "NSSM install failed; you can skip this if you don't plan to use `agentry service install`."
        } else {
            Refresh-Path
            Write-OK "NSSM installed"
        }
    }
} else {
    Write-Skip "NSSM install skipped (-SkipNssm)"
}

# -----------------------------------------------------------------------------
# 7. ~/.agentry/ host config + templates
# -----------------------------------------------------------------------------

Write-Step "Setting up Agentry user directory ($env:USERPROFILE\Agentry)"

# Visible folder under user profile so it's easy to find in Explorer.
# Linux uses the dot-folder convention; Windows uses a regular folder.
$agentryDir = Join-Path $env:USERPROFILE 'Agentry'
$stateDir = Join-Path $agentryDir 'state'
$logsDir = Join-Path $agentryDir 'logs'
foreach ($d in @($agentryDir, $stateDir, $logsDir)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        Write-OK "created $d"
    } else {
        Write-Skip "$d already exists"
    }
}

# Drop template .env / pipeline.local.toml from the repo (or fetch from web
# if running via iwr | iex with no clone).
$envPath = Join-Path $agentryDir '.env'
$tomlPath = Join-Path $agentryDir 'pipeline.local.toml'

# Find the script's own dir if running locally; otherwise download templates.
$scriptDir = $null
if ($PSScriptRoot) { $scriptDir = $PSScriptRoot }
$repoRoot = if ($scriptDir) { Split-Path $scriptDir -Parent } else { $null }

function Get-Template($name, $localFile, $repoUrlPath) {
    if ($repoRoot -and (Test-Path (Join-Path $repoRoot $localFile))) {
        Get-Content -Path (Join-Path $repoRoot $localFile) -Raw
    } else {
        $url = "https://raw.githubusercontent.com/vinu-dev/agentry/main/$repoUrlPath"
        try {
            (Invoke-WebRequest -UseBasicParsing -Uri $url).Content
        } catch {
            Write-Warn "could not fetch $name from $url"
            return $null
        }
    }
}

if (-not (Test-Path $envPath)) {
    $envBody = Get-Template '.env.example' '.env.example' '.env.example'
    if ($envBody) {
        Set-Content -Path $envPath -Value $envBody -NoNewline
        Write-OK "wrote $envPath (template — fill in your secrets)"
    }
} else {
    Write-Skip "$envPath already exists; not overwriting"
}

if (-not (Test-Path $tomlPath)) {
    $tomlBody = Get-Template 'pipeline.example.toml' 'pipeline.example.toml' 'pipeline.example.toml'
    if ($tomlBody) {
        Set-Content -Path $tomlPath -Value $tomlBody -NoNewline
        Write-OK "wrote $tomlPath"
    }
} else {
    Write-Skip "$tomlPath already exists; not overwriting"
}

# -----------------------------------------------------------------------------
# 8. Broadcast environment change so other shells pick up new PATH
# -----------------------------------------------------------------------------

Broadcast-EnvChange

# -----------------------------------------------------------------------------
# 9. Verify
# -----------------------------------------------------------------------------

Write-Step "Verifying install"

$verifyOk = $true
foreach ($cmd in @('python', 'node', 'npm', 'claude', 'codex', 'agentry')) {
    if (Test-Command $cmd) {
        Write-OK "$cmd on PATH"
    } else {
        Write-Warn "$cmd NOT on PATH (may need to open a new shell)"
        $verifyOk = $false
    }
}

if ($verifyOk) {
    Write-Host "`n=== Install complete ===" -ForegroundColor Green
    & agentry --version
}

# -----------------------------------------------------------------------------
# 10. Next steps (the parts the script genuinely cannot automate)
# -----------------------------------------------------------------------------

Write-Host @"

Your Agentry data folder: $agentryDir
This is where your secrets, host config, logs, and state live. To uninstall
later, run scripts/uninstall.ps1 — it removes this folder (and the service,
and the npm globals) cleanly.

Next steps (you must do these — they need your browser / credentials):

  1. Authenticate the LLM CLIs (opens your browser):

         claude login            # uses your Anthropic Pro/Max subscription
         codex login             # uses your ChatGPT subscription

  2. Fill in $envPath. The ONLY required value is GITHUB_TOKEN:

         GITHUB_TOKEN=ghp_...                    # PAT: github.com/settings/tokens

     Everything else is optional:
       - DISCORD_WEBHOOK_URL — push notifications (skip if you'll just read logs)
       - ANTHROPIC_API_KEY / OPENAI_API_KEY — API fallback when subs rate-limit
       - other variables are referenced only by specific role rule files

  3. Run agentry against a target repo:

         cd <your-target-repo>
         agentry doctor --init-labels            # creates the 6 labels in the target
         agentry start                           # foreground; Ctrl-C to stop

     OR install as an always-on Windows Service:

         agentry service install                 # requires NSSM (already installed)

If 'claude' / 'codex' / 'agentry' weren't on PATH in the verify step above,
open a new cmd/PowerShell window and try again — the install added them to
your user PATH but the current shell may need to refresh.

"@ -ForegroundColor Cyan
