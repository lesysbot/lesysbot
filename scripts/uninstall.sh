#!/usr/bin/env bash
# LeSysBot uninstall script — Linux
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

# The compact 8-row cut — this screen isn't cleared, so it stays out of the way.
# See the note in install.sh for why this is sed and not printf.
logo() {
    local f="$REPO_DIR/assets/brand/banner-small.txt"
    [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" && -f "$f" ]] || return 0
    printf '\n'; sed 's/^/  /' "$f"; printf '\n'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

logo
hr
printf "  LeSysBot Uninstaller\n"
hr

# ── 1. Remove the systemd --user service ──────────────────────────────────────
remove_service() {
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
        read -r -p "  Disable auto-start at boot (loginctl disable-linger)? [y/N] " ans
        if is_yes "$ans"; then
            loginctl disable-linger "$USER" && ok "Linger disabled"
        fi
    fi
}

remove_service

# ── 1b. Legacy sudoers rules ──────────────────────────────────────────────────
# Nothing LeSysBot ships needs root any more, so uninstall stays password-free:
# a leftover rule from an old shutdown-wake install is reported, not deleted
# (removing it would make this script prompt for a sudo password).
for rule in /etc/sudoers.d/lesysbot-rtcwake /etc/sudoers.d/lesysbot-shutdown-wake; do
    if [[ -f "$rule" ]]; then
        warn "Leftover sudoers rule from an older version: $rule"
        info "  No current tool uses it. Remove it with:  sudo rm $rule"
    fi
done

# ── 2. Uninstall Python package ───────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    command -v "$cmd" &>/dev/null && PYTHON="$cmd" && break
done

if [[ -n "$PYTHON" ]]; then
    info "Removing lesysbot package …"
    if $PYTHON -m pip show lesysbot &>/dev/null; then
        $PYTHON -m pip uninstall lesysbot -y --quiet
        ok "Package uninstalled"
    else
        warn "Package not found in pip — skipping"
    fi
else
    warn "Python not found — package not removed"
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
    read -r -p "  Stop the Grafana dashboard stack? [y/N] " ans
    if is_yes "$ans"; then
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
    read -r -p "  Remove your config, tools and logs in $DATA_DIR? [y/N] " ans
    if is_yes "$ans"; then
        rm -rf "$DATA_DIR" && ok "Removed $DATA_DIR"
    else
        info "Kept $DATA_DIR (edit or delete it manually later)"
    fi
fi

hr
ok "LeSysBot has been uninstalled."
printf "\n  Optional cleanup:\n"
printf "    rm -rf %s          # config, tools and logs\n\n" "$DATA_DIR"
