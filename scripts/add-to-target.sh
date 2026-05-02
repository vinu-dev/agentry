#!/usr/bin/env bash
# Drop the agentry/ folder + role-file skeletons into the current target repo.
#
# Run this from INSIDE the target repository (e.g. `cd home-monitor` first).
# It downloads template files from the agentry repo on GitHub and writes
# them into the target. Existing files are NOT overwritten unless --force.
#
# Usage:
#   cd <your-target-repo>
#   curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash
#
# Flags (env vars):
#   AGENTRY_FORCE=1     overwrite existing files in agentry/ and docs/ai/roles/
#   AGENTRY_BRANCH=foo  fetch templates from a non-main branch (default: main)

set -euo pipefail

if [[ -t 1 ]]; then
    C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_GRAY='\033[90m'; C_RESET='\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_GRAY=''; C_RESET=''
fi
step() { echo -e "\n${C_CYAN}==> $1${C_RESET}"; }
ok()   { echo -e "    ${C_GREEN}[OK]${C_RESET} $1"; }
skip() { echo -e "    ${C_GRAY}[SKIP]${C_RESET} $1"; }
warn() { echo -e "    ${C_YELLOW}[WARN]${C_RESET} $1"; }

FORCE="${AGENTRY_FORCE:-0}"
BRANCH="${AGENTRY_BRANCH:-main}"
BASE="https://raw.githubusercontent.com/vinu-dev/agentry/$BRANCH/src/agentry/defaults/standard"

CWD="$(pwd)"

step "Adding agentry to $CWD"

if [[ ! -d ".git" ]]; then
    warn "no .git in this directory — are you in a target repo? continuing anyway"
fi

mkdir -p agentry

# Files to drop into agentry/
declare -a AGENTRY_FILES=(
    "config.yml"
    "start.ps1"
    "start.sh"
    ".env.example"
    ".gitignore"
    "README.md"
)

for name in "${AGENTRY_FILES[@]}"; do
    dst="agentry/$name"
    if [[ -f "$dst" && "$FORCE" != "1" ]]; then
        skip "$dst (already exists; AGENTRY_FORCE=1 to overwrite)"
        continue
    fi
    if curl -fsSL "$BASE/$name" -o "$dst.tmp"; then
        mv "$dst.tmp" "$dst"
        ok "wrote $dst"
    else
        warn "could not fetch $BASE/$name"
        rm -f "$dst.tmp"
    fi
done

chmod +x agentry/start.sh 2>/dev/null || true

# Substitute target_repo in config.yml from git remote.
if [[ -f "agentry/config.yml" ]]; then
    REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$REMOTE" =~ github\.com[:/]([^/]+/[^/.]+)(\.git)?$ ]]; then
        REPO="${BASH_REMATCH[1]}"
        sed -i.bak "s|<owner>/<repo>|$REPO|g" "agentry/config.yml" 2>/dev/null || true
        rm -f "agentry/config.yml.bak"
        ok "set target_repo to $REPO in agentry/config.yml"
    fi
fi

# -----------------------------------------------------------------------------

step "Adding role rule file skeletons under docs/ai/roles/"
mkdir -p docs/ai/roles

for role in researcher architect implementer tester reviewer release; do
    dst="docs/ai/roles/$role.md"
    if [[ -f "$dst" && "$FORCE" != "1" ]]; then
        skip "$dst (already exists)"
        continue
    fi
    if curl -fsSL "$BASE/roles/$role.md" -o "$dst.tmp"; then
        mv "$dst.tmp" "$dst"
        ok "wrote $dst"
    else
        warn "could not fetch $role.md"
        rm -f "$dst.tmp"
    fi
done

# -----------------------------------------------------------------------------

cat <<EOF

${C_CYAN}==> Done.${C_RESET}

Next:

  1. Edit agentry/config.yml — pick which model handles each role
     (current defaults: claude for everything except implementer = codex)

  2. Copy your secrets in:

         cp agentry/.env.example agentry/.env
         \$EDITOR agentry/.env                 # paste your GITHUB_TOKEN

  3. (Optional) Edit docs/ai/roles/*.md with project-specific instructions
     for each role. The bundled skeletons work as-is.

  4. Run agentry:

         ./agentry/start.sh                    # foreground; Ctrl-C to stop

If this is a brand-new machine and you haven't run install-deps.sh yet:

     curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.sh | bash

EOF
