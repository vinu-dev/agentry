#!/usr/bin/env bash
# Agentry uninstaller for Linux.
#
# Cleanly removes everything `scripts/install.sh` installed:
#   - The systemd user service (if registered via `agentry service install`)
#   - The agentry Python package (via pipx)
#   - The npm globals: @anthropic-ai/claude-code and @openai/codex
#   - The user data folder ~/.agentry/
#   - Optionally: Node.js (with --remove-deps; off by default)
#
# Idempotent — safe to re-run; skips what's already absent.
#
# Does NOT touch your `claude login` / `codex login` OAuth credentials
# (those live in places owned by the CLIs themselves) — to fully sign
# out, run `claude logout` and `codex logout` separately.
#
# Usage:
#   bash scripts/uninstall.sh                 # standard uninstall
#   bash scripts/uninstall.sh --keep-config   # preserve ~/.agentry/.env
#   bash scripts/uninstall.sh --remove-deps   # also uninstall Node.js
#
# Or as a one-liner from the public repo:
#   curl -fsSL https://raw.githubusercontent.com/vinu-dev/agentry/main/scripts/uninstall.sh | bash

set -uo pipefail   # not -e; we want to continue on errors so partial state still gets cleaned

if [[ -t 1 ]]; then
    C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_GRAY='\033[90m'; C_RESET='\033[0m'
else
    C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_GRAY=''; C_RESET=''
fi
step() { echo -e "\n${C_CYAN}==> $1${C_RESET}"; }
ok()   { echo -e "    ${C_GREEN}[OK]${C_RESET} $1"; }
skip() { echo -e "    ${C_GRAY}[SKIP]${C_RESET} $1"; }
warn() { echo -e "    ${C_YELLOW}[WARN]${C_RESET} $1"; }
cmd_exists() { command -v "$1" >/dev/null 2>&1; }

KEEP_CONFIG=0
REMOVE_DEPS=0
for a in "$@"; do
    case "$a" in
        --keep-config) KEEP_CONFIG=1 ;;
        --remove-deps) REMOVE_DEPS=1 ;;
        -h|--help)
            grep '^#' "$0" | head -30
            exit 0
            ;;
        *) warn "unknown arg: $a (ignored)" ;;
    esac
done

AGENTRY_DIR="$HOME/.agentry"

# -----------------------------------------------------------------------------
# 1. Stop and remove the systemd user service (if present)
# -----------------------------------------------------------------------------

step "Removing agentry systemd user service (if installed)"

if cmd_exists systemctl; then
    if systemctl --user list-unit-files agentry.service 2>/dev/null | grep -q agentry; then
        systemctl --user stop agentry.service 2>/dev/null || true
        systemctl --user disable agentry.service 2>/dev/null || true
        ok "stopped + disabled agentry.service"
    else
        skip "no agentry.service registered"
    fi
    UNIT="$HOME/.config/systemd/user/agentry.service"
    if [[ -f "$UNIT" ]]; then
        rm -f "$UNIT"
        systemctl --user daemon-reload 2>/dev/null || true
        ok "removed $UNIT"
    fi
else
    skip "systemctl not present"
fi

# -----------------------------------------------------------------------------
# 2. Uninstall agentry (try pipx first, then pip --user)
# -----------------------------------------------------------------------------

step "Uninstalling agentry Python package"

if cmd_exists pipx && pipx list 2>/dev/null | grep -q '^   package agentry'; then
    pipx uninstall agentry || true
    ok "uninstalled via pipx"
elif cmd_exists pipx; then
    # pipx is present but agentry isn't installed via it; try pip too.
    pipx uninstall agentry 2>/dev/null || true
fi

if cmd_exists pip3; then
    pip3 uninstall -y agentry 2>/dev/null || true
elif cmd_exists pip; then
    pip uninstall -y agentry 2>/dev/null || true
fi
ok "agentry removed (or was already absent)"

# -----------------------------------------------------------------------------
# 3. Uninstall the LLM CLIs (npm globals)
# -----------------------------------------------------------------------------

step "Removing npm globals (claude-code + codex)"

if cmd_exists npm; then
    npm uninstall -g '@anthropic-ai/claude-code' 2>/dev/null || true
    ok "removed @anthropic-ai/claude-code"
    npm uninstall -g '@openai/codex' 2>/dev/null || true
    ok "removed @openai/codex"
else
    skip "npm not on PATH"
fi

# -----------------------------------------------------------------------------
# 4. Remove the user data folder
# -----------------------------------------------------------------------------

step "Cleaning up $AGENTRY_DIR"

if [[ -d "$AGENTRY_DIR" ]]; then
    if [[ "$KEEP_CONFIG" -eq 1 ]]; then
        for sub in state logs workspaces; do
            if [[ -d "$AGENTRY_DIR/$sub" ]]; then
                rm -rf "$AGENTRY_DIR/$sub"
                ok "removed $AGENTRY_DIR/$sub"
            fi
        done
        ok "kept $AGENTRY_DIR/.env and pipeline.local.toml (--keep-config)"
    else
        rm -rf "$AGENTRY_DIR"
        ok "removed $AGENTRY_DIR"
    fi
else
    skip "$AGENTRY_DIR not present"
fi

# -----------------------------------------------------------------------------
# 5. Optionally remove Node.js (--remove-deps)
# -----------------------------------------------------------------------------

if [[ "$REMOVE_DEPS" -eq 1 ]]; then
    step "Removing Node.js (--remove-deps)"
    SUDO=""
    if [[ $EUID -ne 0 ]] && cmd_exists sudo; then SUDO="sudo"; fi

    if cmd_exists apt-get; then
        $SUDO apt-get remove -y nodejs npm
        $SUDO apt-get autoremove -y
    elif cmd_exists dnf; then
        $SUDO dnf remove -y nodejs npm
    elif cmd_exists pacman; then
        $SUDO pacman -Rns --noconfirm nodejs npm
    elif cmd_exists zypper; then
        $SUDO zypper -n remove nodejs npm
    elif cmd_exists apk; then
        $SUDO apk del nodejs npm
    else
        warn "unknown package manager; remove nodejs manually"
    fi
    ok "Node.js removed"
else
    skip "Keeping Node.js (use --remove-deps to also remove)"
fi

# -----------------------------------------------------------------------------
# 6. PATH cleanup hint
# -----------------------------------------------------------------------------

step "PATH cleanup"

NPM_BIN="$HOME/.npm-global/bin"
SHELL_RC=""
case "${SHELL:-}" in
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
esac

if [[ -n "$SHELL_RC" && -f "$SHELL_RC" ]] && grep -qF "$NPM_BIN" "$SHELL_RC"; then
    if [[ "$REMOVE_DEPS" -eq 1 ]]; then
        # Remove the line we added.
        sed -i.agentry-uninstall.bak "/Added by agentry installer/d; \\#$NPM_BIN#d" "$SHELL_RC" 2>/dev/null || true
        ok "removed agentry PATH addition from $SHELL_RC"
    else
        skip "leaving $NPM_BIN in $SHELL_RC (other npm tools may need it; --remove-deps to clean)"
    fi
fi

# -----------------------------------------------------------------------------
# 7. Summary
# -----------------------------------------------------------------------------

echo -e "\n${C_GREEN}=== Uninstall complete ===${C_RESET}"

cat <<EOF

What was removed:
  - agentry systemd user service (if registered)
  - agentry Python package
  - npm globals: @anthropic-ai/claude-code, @openai/codex
$( [[ "$KEEP_CONFIG" -eq 1 ]] && echo "  - $AGENTRY_DIR/{state,logs,workspaces}" || echo "  - $AGENTRY_DIR (entire user data folder)" )
$( [[ "$REMOVE_DEPS" -eq 1 ]] && echo "  - Node.js + npm" )

$( [[ "$KEEP_CONFIG" -eq 1 ]] && echo "Kept (per --keep-config):" )
$( [[ "$KEEP_CONFIG" -eq 1 ]] && echo "  - $AGENTRY_DIR/.env" )
$( [[ "$KEEP_CONFIG" -eq 1 ]] && echo "  - $AGENTRY_DIR/pipeline.local.toml" )

$( [[ "$REMOVE_DEPS" -eq 0 ]] && echo "What was kept (use --remove-deps to also remove):" )
$( [[ "$REMOVE_DEPS" -eq 0 ]] && echo "  - Node.js + npm" )

To fully sign out of the LLM subscriptions:
  - claude logout
  - codex logout
  (these manage credentials in their own locations, not in $AGENTRY_DIR)

EOF
