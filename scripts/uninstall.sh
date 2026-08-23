#!/usr/bin/env bash
# LeSysBot uninstall script — Linux & macOS
# Usage: bash scripts/uninstall.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { printf "${CYAN}  →  ${NC}%s\n"   "$*"; }
ok()   { printf "${GREEN}  ✓  ${NC}%s\n"  "$*"; }
warn() { printf "${YELLOW}  !  ${NC}%s\n" "$*"; }
hr()   { printf '%0.s─' {1..60}; printf '\n'; }

# Answer test for the y/N prompts below. This is a function rather than
# `[[ "${ans,,}" == y ]]` because `${var,,}` is bash 4 and macOS ships bash 3.2
# as /bin/bash — there it fails at *runtime* ("bad substitution"), which under
# `set -e` aborted this script half-way through an uninstall. `bash -n` does not
# catch it; tests/test_shell_portability.py does.
is_yes() { case "$1" in [Yy]|[Yy][Ee][Ss]) return 0 ;; *) return 1 ;; esac; }

# Prompt, but survive a non-interactive run. Every question here is destructive
# and defaults to "no", so with no terminal to answer them the right move is to
# take that default and carry on. Doing this with a bare `read` cost an exit 1
# half-way through the uninstall: with stdin at /dev/null `read` hits EOF and
# returns non-zero, `set -e` aborts on it, and the script died before its own
# summary — leaving the user with a partial uninstall and no idea why. `|| true`
# alone would not be enough either, because `set -u` then trips over the unset
# answer on the next line.
ask_yn() {
    local prompt="$1" ans=""
    [[ -t 0 ]] || return 1
    read -r -p "$prompt" ans || return 1
    is_yes "$ans"
}

# The compact 8-row cut — this screen isn't cleared, so it stays out of the way.
# See the note in install.sh for why this is sed and not printf.
logo() {
    local f="$REPO_DIR/assets/brand/banner-small.txt"
    [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" && -f "$f" ]] || return 0
    printf '\n'; sed 's/^/  /' "$f"; printf '\n'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

OS="$(uname -s)"

logo
hr
printf "  LeSysBot Uninstaller\n"
hr

# ── 1. Remove platform service ────────────────────────────────────────────────
remove_linux() {
    local stopped=false disabled=false removed=false

    if systemctl --user is-active --quiet lesysbot 2>/dev/null; then
        systemctl --user stop lesysbot
        stopped=true
    fi
    if systemctl --user is-enabled --quiet lesysbot 2>/dev/null; then
        systemctl --user disable lesysbot
        disabled=true
    fi

    UNIT_FILE="$HOME/.config/systemd/user/lesysbot.service"
    if [[ -f "$UNIT_FILE" ]]; then
        rm "$UNIT_FILE"
        systemctl --user daemon-reload
        removed=true
    fi

    if $removed; then
        ok "systemd service removed"
    else
        warn "No systemd service file found — skipping"
    fi

    # Optionally disable linger (only if user wants it)
    if command -v loginctl &>/dev/null && loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
        if ask_yn "  Disable auto-start at boot (loginctl disable-linger)? [y/N] "; then
            loginctl disable-linger "$USER" && ok "Linger disabled"
        fi
    fi
}

remove_macos() {
    PLIST_FILE="$HOME/Library/LaunchAgents/com.lesysbot.lesysbot.plist"
    if [[ -f "$PLIST_FILE" ]]; then
        launchctl unload -w "$PLIST_FILE" 2>/dev/null || true
        rm "$PLIST_FILE"
        ok "LaunchAgent removed"
    else
        warn "No LaunchAgent plist found — skipping"
    fi
}

# The service lives at a fixed per-user path — LESYSBOT_INSTALL_DIR and
# LESYSBOT_BIN_DIR do not move it — so without this guard a sandboxed test run
# would tear down the real machine's service. Same knob install.sh honours.
if [[ -n "${LESYSBOT_SKIP_SERVICE:-}" ]]; then
    info "Leaving the background service alone (LESYSBOT_SKIP_SERVICE set)."
else
    case "$OS" in
        Linux*)  remove_linux  ;;
        Darwin*) remove_macos  ;;
        *)       warn "Unknown OS — skipping service removal" ;;
    esac
fi

# ── 2. Remove the program ─────────────────────────────────────────────────────
# install.sh builds a venv at $INSTALL_DIR/venv and links a shim into $BIN_DIR,
# so that is what has to go. This used to only run `pip uninstall lesysbot`
# against the *system* python, which is where a pre-installer `pip install`
# used to land — against a venv install that finds nothing, and the uninstall
# left a fully working `lesysbot` on PATH. Both paths are handled now: the venv
# first, then pip as the legacy fallback.
INSTALL_DIR="${LESYSBOT_INSTALL_DIR:-$HOME/.local/share/lesysbot}"
BIN_DIR="${LESYSBOT_BIN_DIR:-$HOME/.local/bin}"
VENV="$INSTALL_DIR/venv"

# Drop the shim only when it actually resolves into the venv being removed —
# a `lesysbot` further along PATH belongs to someone else (pipx, a distro
# package, a second --prefix install) and is not ours to delete.
SHIM="$BIN_DIR/lesysbot"
if [[ -e "$SHIM" ]]; then
    if [[ "$(readlink "$SHIM" 2>/dev/null)" == "$VENV"/* ]] \
       || grep -qF "$VENV/bin/lesysbot" "$SHIM" 2>/dev/null; then
        rm -f "$SHIM" && ok "Removed $SHIM"
    else
        warn "$SHIM does not point at $VENV — left alone"
    fi
fi

if [[ -d "$VENV" ]]; then
    rm -rf "$VENV" && ok "Removed the venv at $VENV"
fi

# The installer drops a copy of itself here (self_copy) so an update needs no
# re-download. Remove it, then the directory if nothing else is using it.
rm -f "$INSTALL_DIR/install.sh"
rmdir "$INSTALL_DIR" 2>/dev/null && ok "Removed $INSTALL_DIR" || true

# Legacy fallback: installs that predate install.sh went into the user's python.
PYTHON=""
for cmd in python3 python; do
    command -v "$cmd" &>/dev/null && PYTHON="$cmd" && break
done

if [[ -n "$PYTHON" ]] && $PYTHON -m pip show lesysbot &>/dev/null; then
    info "Removing an older pip-installed lesysbot …"
    $PYTHON -m pip uninstall lesysbot -y --quiet && ok "Package uninstalled"
fi

# ── 2b. Dashboard stack (Grafana/Prometheus) ──────────────────────────────────
# Setup starts this by default, so uninstall offers to take it down. Both paths
# only *stop* things: `start.sh down` omits -v so history in the Docker volumes
# survives, and the macOS path stops the brew services without uninstalling the
# formulae. No sudo — docker and brew both run unprivileged.
DATA_DIR="${LESYSBOT_HOME:-$HOME/.lesysbot}"
STACK_DIR="$DATA_DIR/dashboard"
MON_START="$STACK_DIR/scripts/start.sh"
MON_BREW="$STACK_DIR/scripts/install-macos.sh"
# macOS can have been set up either way (brew services or Docker Desktop), so ask
# once and stop whichever is actually there.
HAS_BREW_STACK=false
[[ "$(uname -s)" == "Darwin" && -f "$MON_BREW" ]] && command -v brew &>/dev/null \
    && HAS_BREW_STACK=true
HAS_DOCKER_STACK=false
[[ -x "$MON_START" ]] && command -v docker &>/dev/null && HAS_DOCKER_STACK=true

if [[ "$HAS_BREW_STACK" == true || "$HAS_DOCKER_STACK" == true ]]; then
    if ask_yn "  Stop the Grafana dashboard stack? [y/N] "; then
        if [[ "$HAS_BREW_STACK" == true ]]; then
            bash "$MON_BREW" down &>/dev/null && ok "Dashboard services stopped" \
                || warn "Could not stop the dashboard services"
            # `down` only unloads the metrics collector's agent; drop the plist
            # too, or launchd keeps firing it every 15s against a script that
            # step 3 below may be about to delete.
            METRICS_PLIST="$HOME/Library/LaunchAgents/com.lesysbot.macos-metrics.plist"
            [[ -f "$METRICS_PLIST" ]] && rm -f "$METRICS_PLIST" \
                && ok "Metrics collector agent removed"
            info "Grafana/Prometheus stay installed — remove them yourself with:"
            info "  brew uninstall grafana prometheus node_exporter"
        fi
        if [[ "$HAS_DOCKER_STACK" == true ]]; then
            "$MON_START" down &>/dev/null && ok "Dashboard containers stopped" \
                || warn "Could not stop the containers (is Docker running?)"
        fi
    else
        info "Left the dashboard stack running"
    fi
fi

# ── 3. Per-user data home (config, tools, logs) ───────────────────────────────
if [[ -d "$DATA_DIR" ]]; then
    if ask_yn "  Remove your config, tools and logs in $DATA_DIR? [y/N] "; then
        rm -rf "$DATA_DIR" && ok "Removed $DATA_DIR"
    else
        info "Kept $DATA_DIR (edit or delete it manually later)"
    fi
fi

hr
ok "LeSysBot has been uninstalled."
printf "\n  Optional cleanup:\n"
printf "    rm -rf %s          # config, tools and logs\n" "$DATA_DIR"
printf "    rm -rf ~/Library/Logs/lesysbot   # macOS stdout/stderr logs\n\n"
