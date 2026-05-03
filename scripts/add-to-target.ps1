<#
.SYNOPSIS
    Drop the agentry/ folder + role-file skeletons into the current target repo.

.DESCRIPTION
    Run this from INSIDE the target repository (e.g. `cd home-monitor` first).
    It downloads template files from the agentry repo on GitHub and writes
    them into the target. Existing files are NOT overwritten unless -Force.

    After this script:
      <target>/agentry/                   ← visible folder (gtest-style)
        config.yml
        start.ps1                          ← run this every time
        start.sh
        .env.example                       ← copy to .env, fill GITHUB_TOKEN
        .gitignore
        README.md
      <target>/docs/ai/roles/              ← skeleton role rule files
        researcher.md
        architect.md
        implementer.md
        tester.md
        reviewer.md
        release.md

    Then:
      1. Edit agentry\config.yml (which model per role)
      2. Copy agentry\.env.example to agentry\.env, fill in GITHUB_TOKEN
      3. Edit docs\ai\roles\*.md if you want project-specific rules
      4. Run .\agentry\start.ps1

.EXAMPLE
    cd C:\projects\rpi-home-monitor
    iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.ps1 | iex

.PARAMETER Force
    Overwrite existing files in agentry/ and docs/ai/roles/.

.PARAMETER Branch
    Branch of the agentry repo to fetch templates from (default: main).
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "    [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Warn($msg) { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }

$base = "https://raw.githubusercontent.com/vinu-dev/agentry/$Branch/src/agentry/defaults/standard"
$cwd = (Get-Location).Path
$agentryRef = $Branch
try {
    $remoteRef = & git ls-remote https://github.com/vinu-dev/agentry.git "refs/heads/$Branch" 2>$null
    if ($LASTEXITCODE -eq 0 -and $remoteRef -match '^([0-9a-f]{40})\s') {
        $agentryRef = $matches[1]
    }
} catch {}

# -----------------------------------------------------------------------------

Write-Step "Adding agentry to $cwd"

if (-not (Test-Path '.git')) {
    Write-Warn "no .git in this directory — are you in a target repo? continuing anyway"
}

# Files to drop into agentry/
$agentryFiles = @{
    'config.yml'    = "$base/config.yml"
    'start.ps1'     = "$base/start.ps1"
    'start.sh'      = "$base/start.sh"
    '.env.example'  = "$base/.env.example"
    '.gitignore'    = "$base/.gitignore"
    'README.md'     = "$base/README.md"
}

New-Item -ItemType Directory -Force -Path 'agentry' | Out-Null

foreach ($name in $agentryFiles.Keys) {
    $dst = "agentry\$name"
    if ((Test-Path $dst) -and -not $Force) {
        Write-Skip "$dst (already exists; use -Force to overwrite)"
        continue
    }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $agentryFiles[$name] -OutFile $dst
        if ($name -in @('start.ps1', 'start.sh')) {
            $content = Get-Content $dst -Raw
            if ($name -eq 'start.ps1') {
                $content = $content -replace "\`$AgentryRef = '[^']+'", "`$AgentryRef = '$agentryRef'"
            } else {
                $content = $content -replace 'AGENTRY_REF="\$\{AGENTRY_INSTALL_REF:-[^}]+\}"', "AGENTRY_REF=`"`$`{AGENTRY_INSTALL_REF:-$agentryRef`}`""
            }
            $content |
                Set-Content $dst -NoNewline
        }
        Write-OK "wrote $dst"
    } catch {
        Write-Warn "could not fetch $($agentryFiles[$name]): $_"
    }
}

# Substitute target_repo in config.yml if we can detect the gh remote.
$cfgPath = 'agentry\config.yml'
if (Test-Path $cfgPath) {
    try {
        $remote = & git remote get-url origin 2>$null
        if ($remote -match 'github\.com[:/]([^/]+/[^/.]+)(\.git)?') {
            $repo = $matches[1]
            (Get-Content $cfgPath -Raw) -replace '<owner>/<repo>', $repo |
                Set-Content $cfgPath -NoNewline
            Write-OK "set target_repo to $repo in $cfgPath"
        }
    } catch {}
}

# -----------------------------------------------------------------------------

# Role rule file skeletons under docs/ai/roles/
Write-Step "Adding role rule file skeletons under docs/ai/roles/"

New-Item -ItemType Directory -Force -Path 'docs/ai/roles' | Out-Null

foreach ($role in @('researcher','architect','implementer','tester','reviewer','release')) {
    $dst = "docs\ai\roles\$role.md"
    if ((Test-Path $dst) -and -not $Force) {
        Write-Skip "$dst (already exists)"
        continue
    }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$base/roles/$role.md" -OutFile $dst
        Write-OK "wrote $dst"
    } catch {
        Write-Warn "could not fetch $role.md: $_"
    }
}

# -----------------------------------------------------------------------------

Write-Host @"

==> Done.

Next:

  1. Edit agentry\config.yml — pick which model handles each role
     (current defaults: claude for everything except implementer = codex)

  2. Copy your secrets in:

         Copy-Item agentry\.env.example agentry\.env
         notepad agentry\.env             # paste your GITHUB_TOKEN

  3. (Optional) Edit docs\ai\roles\*.md with project-specific instructions
     for each role. The bundled skeletons work as-is.

  4. Run agentry:

         .\agentry\start.ps1              # foreground; Ctrl-C to stop

If this is a brand-new machine and you haven't run install-deps.ps1 yet:

     iwr -useb https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.ps1 | iex

"@ -ForegroundColor Cyan

Write-Host "Agentry install ref pinned in start scripts: $agentryRef" -ForegroundColor Cyan
