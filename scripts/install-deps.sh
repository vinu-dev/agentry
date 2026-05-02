#!/usr/bin/env bash
# Agentry — install machine-wide dependencies (Linux).
#
# Installs ONLY the things that need to live on your machine:
#   - Python 3.11+
#   - Node.js + npm
#   - Claude Code CLI (npm install -g @anthropic-ai/claude-code)
#   - OpenAI Codex CLI (npm install -g @openai/codex)
#
# Does NOT install agentry — that gets pip-installed into a local venv
# inside each target repo by `agentry/start.sh`.
#
# Idempotent. Safe to re-run.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/install-deps.sh | bash

set -euo pipefail

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
# Python
# -----------------------------------------------------------------------------

step "Python 3.11+"
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
        *) err "unknown package manager; install python3.11+ manually"; exit 1 ;;
    esac
    ok "Python installed"
else
    skip "Python 3.11+ already present"
fi

# -----------------------------------------------------------------------------
# Node.js
# -----------------------------------------------------------------------------

step "Node.js"
if cmd_exists node && [[ "$FORCE" != "1" ]]; then
    skip "Node.js already present ($(node --version))"
else
    case "$PKG" in
        apt)    curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -; $SUDO apt-get install -y nodejs ;;
        dnf)    $SUDO dnf install -y nodejs npm ;;
        pacman) $SUDO pacman -S --noconfirm nodejs npm ;;
        zypper) $SUDO zypper -n install nodejs npm ;;
        apk)    $SUDO apk add --no-cache nodejs npm ;;
        *) err "unknown package manager; install nodejs+npm manually"; exit 1 ;;
    esac
    ok "Node.js installed: $(node --version)"
fi

# Make npm globals work without sudo and on a known PATH.
NPM_PREFIX="$HOME/.npm-global"
if ! npm config get prefix >/dev/null 2>&1 || [[ "$(npm config get prefix)" == "/usr"* ]]; then
    npm config set prefix "$NPM_PREFIX" >/dev/null
fi
NPM_BIN="$(npm bin -g 2>/dev/null || echo "$NPM_PREFIX/bin")"
mkdir -p "$NPM_BIN"
case ":$PATH:" in *":$NPM_BIN:"*) ;; *) export PATH="$NPM_BIN:$PATH" ;; esac

SHELL_RC=""
case "${SHELL:-}" in
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */zsh)  SHELL_RC="$HOME/.zshrc"  ;;
esac
if [[ -n "$SHELL_RC" && -f "$SHELL_RC" ]] && ! grep -qF "$NPM_BIN" "$SHELL_RC"; then
    echo "" >> "$SHELL_RC"
    echo "# Added by agentry installer" >> "$SHELL_RC"
    echo "export PATH=\"$NPM_BIN:\$PATH\"" >> "$SHELL_RC"
    ok "added $NPM_BIN to $SHELL_RC"
fi

# -----------------------------------------------------------------------------
# LLM CLIs
# -----------------------------------------------------------------------------

step "Claude Code CLI"
if cmd_exists claude && [[ "$FORCE" != "1" ]]; then
    skip "claude already on PATH"
else
    npm install -g '@anthropic-ai/claude-code'
    ok "Claude Code installed"
fi

step "OpenAI Codex CLI"
if cmd_exists codex && [[ "$FORCE" != "1" ]]; then
    skip "codex already on PATH"
else
    npm install -g '@openai/codex'
    ok "Codex CLI installed"
fi

# -----------------------------------------------------------------------------
# Verify
# -----------------------------------------------------------------------------

step "Verifying"
for c in python3 node npm claude codex; do
    if cmd_exists "$c"; then ok "$c on PATH"; else warn "$c NOT on PATH (open a new shell or 'source $SHELL_RC')"; fi
done

cat <<EOF

${C_CYAN}==> Done with machine setup.${C_RESET}

Next:

  1. Authenticate the LLM CLIs (each opens your browser):

         claude login
         codex login

  2. Add agentry to a target repo. From inside that repo:

         curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/add-to-target.sh | bash

EOF
