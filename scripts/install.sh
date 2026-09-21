#!/usr/bin/env bash
# LeSysBot install script — Linux
# Usage: bash scripts/install.sh
#
# Bootstrap only: check Python, pip-install the package, then hand off to the
# Python setup wizard (`lesysbot setup` — arrow-key/Esc navigation; see
# lesysbot/setup/). Re-run `lesysbot setup` directly anytime to reconfigure
# without reinstalling.
set -euo pipefail

# ── colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()  { printf "${GREEN}  ✓  ${NC}%s\n" "$*"; }
die() { printf "${RED}  ✗  ${NC}%s\n"   "$*" >&2; exit 1; }
hr()  { printf "\n  %s\n" "$(printf '%.0s─' {1..50})"; }

# The pixel mark, indented to match everything else. Skipped unless a human is
# watching a colour terminal — and never a hard failure, since this runs before
# we've even checked that Python exists. `sed` (not printf) because the file is
# raw escape codes: printf would try to read them as a format string.
logo() {
    local f="$REPO_DIR/assets/brand/${1:-banner.txt}"
    [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-}" != "dumb" && -f "$f" ]] || return 0
    sed 's/^/  /' "$f"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

clear
printf "\n"
logo
hr
printf "\n  ${BOLD}LeSysBot Setup${NC}\n"
hr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PYTHON
# ═══════════════════════════════════════════════════════════════════════════════
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    die "Python 3.11+ is required but was not found.
       Install it with your package manager, e.g.:
         Ubuntu/Debian : sudo apt install python3
         Fedora/RHEL   : sudo dnf install python3
         Arch          : sudo pacman -S python"
fi
ok "Python $($PYTHON --version | cut -d' ' -f2)"

# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSTALL PACKAGE
# ═══════════════════════════════════════════════════════════════════════════════
printf "\n  Installing lesysbot package …\n"
cd "$REPO_DIR"
# .[all] = Telegram + Discord extras, so every option the wizard
# offers below works without a second install step.
$PYTHON -m pip install --quiet ".[all]"
ok "Package installed"

LESYSBOT_BIN=""
if command -v lesysbot &>/dev/null; then
    LESYSBOT_BIN="$(command -v lesysbot)"
else
    SCRIPTS="$($PYTHON -c 'import sys, os; print(os.path.join(sys.prefix, "bin"))')"
    [[ -f "$SCRIPTS/lesysbot" ]] && LESYSBOT_BIN="$SCRIPTS/lesysbot"
fi
[[ -n "$LESYSBOT_BIN" ]] || die "Cannot locate the lesysbot binary after install.
       Make sure pip's bin directory is in your PATH, then re-run."
ok "Binary: $LESYSBOT_BIN"

# ═══════════════════════════════════════════════════════════════════════════════
# 3. SETUP WIZARD  (Python — lesysbot/setup/; LESYSBOT_HOME passes through)
# ═══════════════════════════════════════════════════════════════════════════════
exec "$LESYSBOT_BIN" setup --repo "$REPO_DIR"
