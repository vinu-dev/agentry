#!/usr/bin/env bash
# Agentry one-shot installer for Linux.
#
# Installs everything Agentry needs on a Linux host:
#   - python3 + pipx (via apt / dnf / pacman)
#   - Node.js + npm (via apt with NodeSource, or dnf, or pacman)
#   - agentry itself (pipx from public GitHub)
#   - Claude Code CLI (npm install -g @anthropic-ai/claude-code)
#   - OpenAI Codex CLI (npm install -g @openai/codex)
#   - ~/.agentry/ directory with template .env and pipeline.local.toml
#
# The script does NOT run `claude login` / `codex login` (OAuth needs your
# browser) and does NOT fill in your API keys. Those are listed at the end
# as your remaining steps.
#
# Idempotent — safe to re-run. Skips installs that are already present.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install.sh | bash
#
#   # Or from a clone:
#   bash scripts/install.sh
#
# Flags (env vars):
#   AGENTRY_SKIP_NPM_GLOBALS=1   skip the Claude/Codex CLI installs
#   AGENTRY_FORCE=1              reinstall even if components are present

set -euo pipefail

# -----------------------------------------------------------------------------
# Pretty output helpers
# -----------------------------------------------------------------------------

if [[ -t 1 ]]; then
    C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_GRAY='\033[90m'; C_RESET='\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_GRAY=''; C_RESET=''
fi

step() { echo -e "\n${C_CYAN}==> $1${C_RESET}"; }
ok()   { echo -e "    ${C_GREEN}[OK]${C_RESET} $1"; }
skip() { echo -e "    ${C_GRAY}[SKIP]${C_RESET} $1"; }
warn() { echo -e "    ${C_YELLOW}[WARN]${C_RESET} $1"; }
err()  { echo -e "    ${C_RED}[ERR]${C_RESET}  $1" >&2; }

cmd_exists() { command -v "$1" >/dev/null 2>&1; }

FORCE="${AGENTRY_FORCE:-0}"
SKIP_NPM="${AGENTRY_SKIP_NPM_GLOBALS:-0}"

# -----------------------------------------------------------------------------
# Detect package manager
# -----------------------------------------------------------------------------

detect_pkg_manager() {
    if cmd_exists apt-get;     then echo apt
    elif cmd_exists dnf;       then echo dnf
    elif cmd_exists pacman;    then echo pacman
    elif cmd_exists zypper;    then echo zypper
    elif cmd_exists apk;       then echo apk
    else echo unknown; fi
}

PKG=$(detect_pkg_manager)
SUDO=""
if [[ $EUID -ne 0 ]] && cmd_exists sudo; then SUDO="sudo"; fi

step "Detected package manager: $PKG"

# -----------------------------------------------------------------------------
# 1. Python + pipx
# -----------------------------------------------------------------------------

step "Checking Python 3.11+"

PY_OK=0
for cmd in python3 python; do
    if cmd_exists "$cmd"; then
        v=$("$cmd" --version 2>&1 | awk '{print $2}')
        major=$(echo "$v" | cut -d. -f1); minor=$(echo "$v" | cut -d. -f2)
        if [[ "$major" -gt 3 ]] || [[ "$major" -eq 3 && "$minor" -ge 11 ]]; then
            ok "$cmd $v"; PY_OK=1; break
        fi
    fi
done

if [[ "$PY_OK" -ne 1 || "$FORCE" == "1" ]]; then
    case "$PKG" in
        apt)    $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-pip python3-venv ;;
        dnf)    $SUDO dnf install -y python3 python3-pip ;;
        pacman) $SUDO pacman -Sy --noconfirm python python-pip ;;
        zypper) $SUDO zypper -n install python3 python3-pip ;;
        apk)    $SUDO apk add --no-cache python3 py3-pip ;;
        *) err "unknown package manager; install python3.11+ manually and re-run"; exit 1 ;;
    esac
    ok "Python installed"
else
    skip "Python 3.11+ already present"
fi

step "Checking pipx"
if cmd_exists pipx && [[ "$FORCE" != "1" ]]; then
    skip "pipx already present ($(pipx --version))"
else
    case "$PKG" in
        apt)    $SUDO apt-get install -y pipx ;;
        dnf)    $SUDO dnf install -y pipx ;;
        pacman) $SUDO pacman -S --noconfirm python-pipx ;;
        zypper) $SUDO zypper -n install python3-pipx ;;
        apk)    $SUDO apk add --no-cache pipx ;;
        *) python3 -m pip install --user --upgrade pipx ;;
    esac
    pipx ensurepath || true
    # pipx ensurepath modifies ~/.bashrc etc; make available now too:
    if [[ -d "$HOME/.local/bin" ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    ok "pipx installed"
fi

# -----------------------------------------------------------------------------
# 2. Node.js + npm
# -----------------------------------------------------------------------------

step "Checking Node.js"
if cmd_exists node && [[ "$FORCE" != "1" ]]; then
    skip "Node.js already present ($(node --version))"
else
    case "$PKG" in
        apt)
            # Use NodeSource for an up-to-date LTS on Debian/Ubuntu.
            curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -
            $SUDO apt-get install -y nodejs
            ;;
        dnf)
            $SUDO dnf install -y nodejs npm
            ;;
        pacman)
            $SUDO pacman -S --noconfirm nodejs npm
            ;;
        zypper)
            $SUDO zypper -n install nodejs npm
            ;;
        apk)
            $SUDO apk add --no-cache nodejs npm
            ;;
        *)
            err "unknown package manager; install nodejs+npm manually and re-run"
            exit 1
            ;;
    esac
    ok "Node.js installed: $(node --version)"
fi

# Make sure npm globals end up somewhere on PATH without needing sudo.
NPM_PREFIX="$HOME/.npm-global"
if ! npm config get prefix >/dev/null 2>&1 || [[ "$(npm config get prefix)" == "/usr"* ]]; then
    npm config set prefix "$NPM_PREFIX" >/dev/null
fi
NPM_BIN="$(npm bin -g 2>/dev/null || echo "$NPM_PREFIX/bin")"
mkdir -p "$NPM_BIN"

# Add to PATH for this session.
case ":$PATH:" in
    *":$NPM_BIN:"*) ;;
    *) export PATH="$NPM_BIN:$PATH" ;;
esac

# Persist for future shells.
SHELL_RC=""
case "${SHELL:-}" in
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */zsh)  SHELL_RC="$HOME/.zshrc"  ;;
esac
if [[ -n "$SHELL_RC" && -f "$SHELL_RC" ]]; then
    if ! grep -qF "$NPM_BIN" "$SHELL_RC"; then
        echo "" >> "$SHELL_RC"
        echo "# Added by agentry installer" >> "$SHELL_RC"
        echo "export PATH=\"$NPM_BIN:\$PATH\"" >> "$SHELL_RC"
        ok "added $NPM_BIN to $SHELL_RC"
    else
        skip "$NPM_BIN already on PATH in $SHELL_RC"
    fi
fi

# -----------------------------------------------------------------------------
# 3. agentry (pipx)
# -----------------------------------------------------------------------------

step "Installing agentry"
if cmd_exists agentry && [[ "$FORCE" != "1" ]]; then
    skip "agentry already installed: $(agentry --version)"
else
    pipx install --force 'git+https://github.com/vinu-dev/agentry.git' || {
        err "pipx install failed; check the error output above"
        exit 1
    }
    # pipx places shims in ~/.local/bin which should already be on PATH from
    # `pipx ensurepath` — but make sure for this session:
    if [[ -d "$HOME/.local/bin" && ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    ok "agentry installed: $(agentry --version)"
fi

# -----------------------------------------------------------------------------
# 4. Claude Code + Codex CLIs (via npm)
# -----------------------------------------------------------------------------

if [[ "$SKIP_NPM" == "1" ]]; then
    skip "AGENTRY_SKIP_NPM_GLOBALS=1; not installing claude/codex CLIs"
else
    step "Installing Claude Code CLI"
    if cmd_exists claude && [[ "$FORCE" != "1" ]]; then
        skip "claude already on PATH"
    else
        npm install -g '@anthropic-ai/claude-code'
        ok "Claude Code installed"
    fi

    step "Installing OpenAI Codex CLI"
    if cmd_exists codex && [[ "$FORCE" != "1" ]]; then
        skip "codex already on PATH"
    else
        npm install -g '@openai/codex'
        ok "Codex CLI installed"
    fi
fi

# -----------------------------------------------------------------------------
# 5. ~/.agentry/ host config + templates
# -----------------------------------------------------------------------------

step "Setting up Agentry user directory"

# Linux uses ~/.agentry/ (Unix dot-folder convention).
# Windows uses %USERPROFILE%\Agentry\ (visible folder) — handled in install.ps1.
AGENTRY_DIR="$HOME/.agentry"
mkdir -p "$AGENTRY_DIR" "$AGENTRY_DIR/state" "$AGENTRY_DIR/logs"
ok "ensured $AGENTRY_DIR + state/ + logs/"

# Find script's own dir if running locally; otherwise fetch from raw github.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
REPO_ROOT=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../.env.example" ]]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

fetch_template() {
    local local_path="$1"
    local repo_path="$2"
    if [[ -n "$REPO_ROOT" && -f "$REPO_ROOT/$local_path" ]]; then
        cat "$REPO_ROOT/$local_path"
    else
        curl -fsSL "https://raw.githubusercontent.com/vinu-dev/agentry/main/$repo_path"
    fi
}

ENV_FILE="$AGENTRY_DIR/.env"
TOML_FILE="$AGENTRY_DIR/pipeline.local.toml"

if [[ ! -f "$ENV_FILE" ]]; then
    if fetch_template ".env.example" ".env.example" > "$ENV_FILE.tmp" 2>/dev/null; then
        mv "$ENV_FILE.tmp" "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        ok "wrote $ENV_FILE (template — fill in your secrets)"
    else
        warn "could not fetch .env.example; skipping"
    fi
else
    skip "$ENV_FILE already exists; not overwriting"
fi

if [[ ! -f "$TOML_FILE" ]]; then
    if fetch_template "pipeline.example.toml" "pipeline.example.toml" > "$TOML_FILE.tmp" 2>/dev/null; then
        mv "$TOML_FILE.tmp" "$TOML_FILE"
        ok "wrote $TOML_FILE"
    else
        warn "could not fetch pipeline.example.toml; skipping"
    fi
else
    skip "$TOML_FILE already exists; not overwriting"
fi

# -----------------------------------------------------------------------------
# 6. Verify
# -----------------------------------------------------------------------------

step "Verifying install"

VERIFY_OK=1
for c in python3 node npm claude codex agentry; do
    if cmd_exists "$c"; then
        ok "$c on PATH"
    else
        warn "$c NOT on PATH (open a new shell or 'source $SHELL_RC')"
        VERIFY_OK=0
    fi
done

if [[ "$VERIFY_OK" -eq 1 ]]; then
    echo -e "\n${C_GREEN}=== Install complete ===${C_RESET}"
    agentry --version
fi

# -----------------------------------------------------------------------------
# 7. Next steps
# -----------------------------------------------------------------------------

cat <<EOF

${C_CYAN}Next steps (you must do these — they need your browser / credentials):${C_RESET}

  1. Authenticate the LLM CLIs (opens your browser):

         claude login            # uses your Anthropic Pro/Max subscription
         codex login             # uses your ChatGPT subscription

  2. Fill in $ENV_FILE with your actual values:

         GITHUB_TOKEN=ghp_...                    # github.com/settings/tokens
         DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
         ANTHROPIC_API_KEY=sk-ant-...            # optional API fallback
         OPENAI_API_KEY=sk-...                   # optional API fallback

  3. Run agentry against a target repo:

         cd <your-target-repo>
         agentry doctor --init-labels            # creates the 6 labels in the target
         agentry start                           # foreground; Ctrl-C to stop

     OR install as a systemd user service (always-on, survives reboot):

         agentry service install
         systemctl --user status agentry

If any command above isn't on PATH, open a new shell or run:

         source $SHELL_RC

EOF
