#!/bin/sh
# LeSysBot installer — macOS & Linux
#
#   curl -fsSL https://lesysbot.github.io/install.sh | sh
#   curl -fsSL https://lesysbot.github.io/install.sh | sh -s -- --skip-dashboard
#   sh scripts/install.sh                       # from a checkout
#   ~/.local/share/lesysbot/install.sh --uninstall
#
# Finds (or installs) a Python 3.11+, builds an isolated venv, installs LeSysBot
# into it, links a `lesysbot` command onto PATH, gets Ollama and a model ready,
# then hands off to `lesysbot setup --yes`. Nothing here prompts: every decision
# is a default or a flag, so it works piped from curl with no terminal at all.
#
# POSIX sh on purpose — the advertised pipe is `| sh`, and /bin/sh is dash on
# Debian/Ubuntu, where bash syntax ([[ ]], arrays, BASH_SOURCE) is a parse error.
# Keep it that way; `shellcheck --shell=sh scripts/install.sh` is in CI.
#
# Every real decision belongs in `lesysbot setup` (Python, tested, cross-platform).
# This script's whole job is: find an interpreter, install, link, hand off.

set -eu
# pipefail where the shell has it (bash/ksh/zsh); dash has no such option and
# would abort the script under `set -e` if we asked for it unguarded.
# shellcheck disable=SC3040
(set -o pipefail 2>/dev/null) && set -o pipefail || true

REPO="lesysbot/lesysbot"
DEFAULT_MODEL="qwen3.5:4b"
OLLAMA_INSTALLER="https://ollama.com/install.sh"
UV_INSTALLER="https://astral.sh/uv/install.sh"
MARK_BEGIN="# >>> lesysbot >>>"
MARK_END="# <<< lesysbot <<<"

INSTALL_DIR="${LESYSBOT_INSTALL_DIR:-$HOME/.local/share/lesysbot}"
BIN_DIR="${LESYSBOT_BIN_DIR:-$HOME/.local/bin}"
MODEL="${LESYSBOT_MODEL:-$DEFAULT_MODEL}"
REF="${LESYSBOT_REF:-}"
VERSION="${LESYSBOT_VERSION:-}"
NO_MODIFY_PATH="${LESYSBOT_NO_MODIFY_PATH:-}"
SKIP_OLLAMA="${LESYSBOT_SKIP_OLLAMA:-}"
WITH_OLLAMA=""
SKIP_MODEL=""
SKIP_DASHBOARD="${LESYSBOT_SKIP_DASHBOARD:-}"
SKIP_SETUP="${LESYSBOT_SKIP_SETUP:-}"
PROVIDER="${LESYSBOT_SETUP_PROVIDER:-}"
UNINSTALL=""
PURGE=""
REPO_DIR=""
PYTHON=""
PYTHON_NOTE=""
FRESH_VENV="yes"

# ── output ────────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); NC=$(printf '\033[0m')
    GREEN=$(printf '\033[0;32m'); YELLOW=$(printf '\033[0;33m'); RED=$(printf '\033[0;31m')
else
    BOLD=""; DIM=""; NC=""; GREEN=""; YELLOW=""; RED=""
fi

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  %s✓%s  %s\n' "$GREEN" "$NC" "$*"; }
step() { printf '  %s→%s  %s\n' "$BOLD" "$NC" "$*"; }
warn() { printf '  %s!%s  %s\n' "$YELLOW" "$NC" "$*"; }
note() { printf '     %s%s%s\n' "$DIM" "$*" "$NC"; }
die()  { printf '\n  %s✗%s  %s\n\n' "$RED" "$NC" "$*" >&2; exit 1; }
rule() { printf '  ──────────────────────────────────────────────────\n'; }

# Two-column status line: label, then the detail, aligned.
okv()  { printf '  %s✓%s  %-28s %s%s%s\n' "$GREEN" "$NC" "$1" "$DIM" "$2" "$NC"; }

usage() {
    cat <<'EOF'
  LeSysBot installer

  Usage:  curl -fsSL https://lesysbot.github.io/install.sh | sh
          curl -fsSL https://lesysbot.github.io/install.sh | sh -s -- [options]

  Options
    --version X.Y.Z     Install a specific release (default: the latest)
    --ref REF           Install a branch or tag instead
    --prefix DIR        Where the venv goes      (default: ~/.local/share/lesysbot)
    --bin-dir DIR       Where `lesysbot` goes    (default: ~/.local/bin)
    --no-modify-path    Don't touch shell startup files
    --skip-ollama       Don't install Ollama     --with-ollama  install it even if
                                                 that means a sudo password prompt
    --model NAME        Model to pull            (default: qwen3.5:4b)
    --no-model          Don't pull a model
    --skip-dashboard    Don't set up the Grafana dashboard
    --skip-setup        Install the command only; don't configure anything
    --provider P        cli (default), telegram or discord
    --uninstall         Remove LeSysBot, keeping ~/.lesysbot
    --purge             With --uninstall, delete ~/.lesysbot too
    -h, --help          This text

  Scripted installs read LESYSBOT_SETUP_* from the environment — see
  https://lesysbot.github.io/latest/guides/getting-started/
EOF
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --version) VERSION="${2:?--version needs a value}"; shift 2 ;;
            --ref)     REF="${2:?--ref needs a value}"; shift 2 ;;
            --prefix)  INSTALL_DIR="${2:?--prefix needs a value}"; shift 2 ;;
            --bin-dir) BIN_DIR="${2:?--bin-dir needs a value}"; shift 2 ;;
            --model)   MODEL="${2:?--model needs a value}"; shift 2 ;;
            --provider) PROVIDER="${2:?--provider needs a value}"; shift 2 ;;
            --no-modify-path) NO_MODIFY_PATH=1; shift ;;
            --skip-ollama)    SKIP_OLLAMA=1; shift ;;
            --with-ollama)    WITH_OLLAMA=1; SKIP_OLLAMA=""; shift ;;
            --no-model)       SKIP_MODEL=1; shift ;;
            --skip-dashboard) SKIP_DASHBOARD=1; shift ;;
            --skip-setup)     SKIP_SETUP=1; shift ;;
            --uninstall)      UNINSTALL=1; shift ;;
            --purge)          UNINSTALL=1; PURGE=1; shift ;;
            -h|--help)        usage; exit 0 ;;
            *) usage >&2; die "Unknown option: $1" ;;
        esac
    done
}

# ── helpers ───────────────────────────────────────────────────────────────────
have() { command -v "$1" >/dev/null 2>&1; }

# Fetch a URL to stdout. curl is near-universal; wget covers the minimal images
# that ship without it.
fetch() {
    if have curl; then
        curl -fsSL "$1"
    elif have wget; then
        wget -qO- "$1"
    else
        die "Neither curl nor wget is available — install one and re-run."
    fi
}

# The checkout this script lives in, if any. Replaces ${BASH_SOURCE[0]}, which
# dash doesn't have and which means nothing when piped from curl. Used *only* to
# pass --repo to setup from a clone; a piped run must never pass it.
script_dir() {
    case "$0" in */*) ;; *) return 1 ;; esac
    # CDPATH='' (not the bare `CDPATH=` shellcheck flags as SC1007) keeps `cd`
    # from resolving the argument against a user's CDPATH and printing the
    # directory it landed in, which would corrupt the captured path.
    d=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || return 1
    [ -f "$d/install.sh" ] || return 1
    printf '%s\n' "$d"
}

# The pip requirement to install. When LeSysBot is published to PyPI the URL
# branch becomes
#   printf 'lesysbot[telegram,discord]==%s\n' "$VERSION"
# and nothing else in this script changes.
#
# The leaf extras are named rather than [all]: `all` is defined as
# lesysbot[telegram,discord], and a self-referential extra combined with a
# PEP 508 direct-URL requirement is the one pip corner that has misbehaved.
#
# Run from a checkout with no explicit --ref/--version, this installs *that
# checkout* — so a contributor can test a change to the installer without
# pushing it first. Naming a ref always downloads that ref instead.
package_spec() {
    if [ -n "$REPO_DIR" ] && [ -z "$REF" ] && [ -z "$VERSION" ]; then
        printf '%s[telegram,discord]\n' "$REPO_DIR"
    else
        printf 'lesysbot[telegram,discord] @ https://github.com/%s/archive/%s.zip\n' \
               "$REPO" "$(ref_path)"
    fi
}

# What install_package announces it is fetching.
source_label() {
    if [ -n "$REPO_DIR" ] && [ -z "$REF" ] && [ -z "$VERSION" ]; then
        printf 'from this checkout\n'
    else
        printf '%s\n' "$(ref_path)"
    fi
}

# Which git ref to install. An explicit --version/--ref wins; otherwise the
# latest release, so a bad merge to main can't break every new install. Falls
# back to main when there are no releases yet or the API can't be reached.
ref_path() {
    if [ -n "$VERSION" ]; then
        printf 'refs/tags/v%s\n' "${VERSION#v}"
    elif [ -n "$REF" ]; then
        printf '%s\n' "$REF"
    else
        printf '%s\n' "${RESOLVED_REF:-refs/heads/main}"
    fi
}

resolve_latest_release() {
    [ -n "$VERSION" ] && return 0
    [ -n "$REF" ] && return 0
    [ -n "$REPO_DIR" ] && return 0
    tag=$(fetch "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
          | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
          | head -n 1) || tag=""
    if [ -n "$tag" ]; then
        RESOLVED_REF="refs/tags/$tag"
    else
        RESOLVED_REF="refs/heads/main"
    fi
}

# ── Python ────────────────────────────────────────────────────────────────────
python_ok() {
    "$1" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    # `import venv` is part of the test on purpose: Debian and Ubuntu split it
    # into a separate python3-venv package, and without it the venv step fails
    # several lines later with a message about ensurepip that explains nothing.
    for c in python3.13 python3.12 python3.11 python3 python; do
        if have "$c" && python_ok "$c"; then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

# No usable Python: install uv (a single static binary, no root) and let it
# fetch one. UV_NO_MODIFY_PATH because this script owns PATH handling — two
# installers editing the same shell files is how profiles get mangled.
bootstrap_uv_python() {
    step "No Python 3.11+ found — fetching a private one with uv …"
    uv_bin="$HOME/.local/bin/uv"
    have uv && uv_bin=$(command -v uv)
    if [ ! -x "$uv_bin" ]; then
        fetch "$UV_INSTALLER" | env UV_NO_MODIFY_PATH=1 sh >/dev/null 2>&1 || true
    fi
    [ -x "$uv_bin" ] || return 1
    "$uv_bin" python install 3.12 >/dev/null 2>&1 || return 1
    found=$("$uv_bin" python find 3.12 2>/dev/null) || return 1
    [ -n "$found" ] && [ -x "$found" ] || return 1
    PYTHON_NOTE="managed by uv — keep it with: uv python install 3.12"
    printf '%s\n' "$found"
}

ensure_python() {
    if PYTHON=$(find_python); then
        :
    elif PYTHON=$(bootstrap_uv_python); then
        :
    else
        die "No Python 3.11+ found, and the fallback installer (uv) could not run.
     Install Python 3.11 or newer and re-run this command:
       Ubuntu/Debian  sudo apt install python3 python3-venv
       Fedora         sudo dnf install python3
       macOS          brew install python@3.12
       Any            https://www.python.org/downloads/"
    fi
    version=$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
    okv "Python $version" "$PYTHON"
    [ -n "$PYTHON_NOTE" ] && note "$PYTHON_NOTE"
    return 0
}

# ── install ───────────────────────────────────────────────────────────────────
VENV=""

make_venv() {
    VENV="$INSTALL_DIR/venv"
    if [ -x "$VENV/bin/python" ]; then
        FRESH_VENV="no"
    else
        mkdir -p "$INSTALL_DIR"
        rm -rf "$VENV"
        "$PYTHON" -m venv "$VENV" || die "Could not create a virtual environment at $VENV"
    fi
    okv "Environment" "$VENV"
}

install_package() {
    step "Installing LeSysBot ($(source_label)) …"
    set -- --disable-pip-version-check --no-input --quiet
    if [ "$FRESH_VENV" = "no" ]; then
        # The version string is static between releases, so pip would call a
        # moving branch or re-tagged archive "already satisfied" and install
        # nothing at all. Re-running the installer is the documented upgrade
        # path, so it has to genuinely replace what is there.
        set -- "$@" --force-reinstall
    fi
    "$VENV/bin/python" -m pip install "$@" "$(package_spec)" \
        || die "Installing LeSysBot failed — the pip output above says why.
     Report it at https://github.com/$REPO/issues"
    [ -x "$VENV/bin/lesysbot" ] \
        || die "The package installed but the lesysbot command is missing."
    ok "LeSysBot installed"
}

link_shim() {
    mkdir -p "$BIN_DIR"
    if ! ln -sf "$VENV/bin/lesysbot" "$BIN_DIR/lesysbot" 2>/dev/null; then
        # Filesystems without symlinks still deserve a working command.
        printf '#!/bin/sh\nexec "%s/bin/lesysbot" "$@"\n' "$VENV" > "$BIN_DIR/lesysbot"
        chmod +x "$BIN_DIR/lesysbot"
    fi
    okv "Command" "$BIN_DIR/lesysbot"
    PATH="$BIN_DIR:$PATH"
    export PATH
}

on_path() {
    case ":$PATH:" in *":$BIN_DIR:"*) return 0 ;; esac
    return 1
}

# Add BIN_DIR to PATH in the user's shell startup files. Deliberately one
# clearly marked block per file so --uninstall can take it back out exactly, and
# never ~/.bash_profile: on macOS it shadows ~/.profile, and rewriting it has
# bitten every installer that tried.
ensure_path() {
    # link_shim has already put BIN_DIR on this process's PATH, so the question
    # is whether the *user's shell* would find it — PATH_WAS_SET, sampled first.
    if [ "$PATH_WAS_SET" = "yes" ]; then
        okv "PATH" "already includes $BIN_DIR"
        return 0
    fi
    if [ -n "$NO_MODIFY_PATH" ]; then
        warn "$BIN_DIR is not on your PATH (--no-modify-path)."
        note "Add it yourself:  export PATH=\"$BIN_DIR:\$PATH\""
        return 0
    fi
    touched=""
    for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshenv"; do
        # ~/.profile is created if absent (it is the POSIX default and what a
        # login shell reads); the others are only extended when already in use.
        if [ ! -f "$rc" ] && [ "$rc" != "$HOME/.profile" ]; then
            continue
        fi
        if [ -f "$rc" ] && grep -qF "$MARK_BEGIN" "$rc" 2>/dev/null; then
            continue
        fi
        {
            printf '\n%s\n' "$MARK_BEGIN"
            printf 'case ":$PATH:" in *":%s:"*) ;; *) PATH="%s:$PATH" ;; esac\n' \
                   "$BIN_DIR" "$BIN_DIR"
            printf 'export PATH\n'
            printf '%s\n' "$MARK_END"
        } >> "$rc" 2>/dev/null || continue
        touched="$touched ${rc##*/}"
    done
    if [ -n "$touched" ]; then
        okv "PATH" "added $BIN_DIR to$touched"
    else
        warn "$BIN_DIR is not on your PATH and no startup file could be updated."
        note "Add it yourself:  export PATH=\"$BIN_DIR:\$PATH\""
    fi
}

# ── Ollama ────────────────────────────────────────────────────────────────────
# The one step this installer can't always finish by itself. Ollama's own script
# needs root on Linux, and LeSysBot never asks for a password — so where a
# password would be required we print the two lines instead and carry on. The
# install is still usable: the config points at Ollama, and `lesysbot` reports
# the backend as unreachable with the fix.
can_sudo_silently() {
    [ "$(id -u)" = "0" ] && return 0
    have sudo && sudo -n true >/dev/null 2>&1
}

ollama_manual_note() {
    warn "Ollama isn't installed. Installing it on Linux needs root, and this"
    note "installer never asks for your password. Run these two lines:"
    note ""
    note "    curl -fsSL $OLLAMA_INSTALLER | sh"
    note "    ollama pull $MODEL"
    note ""
    note "Using OpenAI or another endpoint instead? \`lesysbot setup\` has it."
}

ensure_ollama() {
    if [ -n "$SKIP_OLLAMA" ]; then
        note "Skipping Ollama (--skip-ollama)."
        return 0
    fi
    if have ollama; then
        okv "Ollama" "already installed"
        return 0
    fi
    case "$(uname -s)" in
        Darwin)
            if have brew; then
                step "Installing Ollama with Homebrew …"
                brew install ollama >/dev/null 2>&1 && brew services start ollama >/dev/null 2>&1 || true
            else
                step "Installing Ollama …"
                fetch "$OLLAMA_INSTALLER" | sh >/dev/null 2>&1 || true
            fi
            ;;
        Linux)
            if [ -n "$WITH_OLLAMA" ] || can_sudo_silently; then
                step "Installing Ollama …"
                fetch "$OLLAMA_INSTALLER" | sh >/dev/null 2>&1 || true
            else
                ollama_manual_note
                return 0
            fi
            ;;
        *)
            warn "Install Ollama for this platform from https://ollama.com/download"
            return 0
            ;;
    esac
    if have ollama; then
        ok "Ollama installed"
    else
        warn "Ollama could not be installed automatically — https://ollama.com/download"
    fi
}

wait_for_ollama() {
    i=0
    while [ "$i" -lt 30 ]; do
        if ollama list >/dev/null 2>&1; then
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done
    return 1
}

pull_model() {
    [ -n "$SKIP_MODEL" ] && return 0
    [ -n "$SKIP_OLLAMA" ] && return 0
    have ollama || return 0
    if ! wait_for_ollama; then
        warn "Ollama is installed but not answering yet — pull the model later with:"
        note "    ollama pull $MODEL"
        return 0
    fi
    if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$MODEL"; then
        okv "Model $MODEL" "already downloaded"
        return 0
    fi
    step "Pulling $MODEL — this can take a few minutes …"
    if ollama pull "$MODEL" >/dev/null 2>&1; then
        ok "Model $MODEL ready"
    else
        warn "Could not pull $MODEL. Do it later with:  ollama pull $MODEL"
    fi
}

# ── setup ─────────────────────────────────────────────────────────────────────
run_setup() {
    if [ -n "$SKIP_SETUP" ]; then
        note "Skipping configuration (--skip-setup). Run \`lesysbot setup\` when ready."
        return 0
    fi
    [ -n "$SKIP_DASHBOARD" ] && export LESYSBOT_SKIP_DASHBOARD=1
    [ -n "$PROVIDER" ] && export LESYSBOT_SETUP_PROVIDER="$PROVIDER"

    printf '\n'
    if [ -z "$SKIP_DASHBOARD" ]; then
        step "Configuring LeSysBot …"
        note "(this also sets up the Grafana dashboard — skip it with --skip-dashboard)"
    else
        step "Configuring LeSysBot …"
    fi
    printf '\n'

    if [ -n "$REPO_DIR" ]; then
        "$BIN_DIR/lesysbot" setup --yes --repo "$REPO_DIR"
    else
        "$BIN_DIR/lesysbot" setup --yes
    fi
}

epilogue() {
    printf '\n'
    rule
    printf '  %sLeSysBot is installed.%s\n\n' "$BOLD" "$NC"
    printf '    %slesysbot chat%s     talk to it in this terminal\n' "$BOLD" "$NC"
    printf '    %slesysbot%s          health, links, and where everything lives\n' "$BOLD" "$NC"
    printf '    %slesysbot setup%s    change any of the answers above\n' "$BOLD" "$NC"
    printf '\n'
    if [ "$PATH_WAS_SET" = "no" ]; then
        say "Open a new terminal first, or run:  export PATH=\"$BIN_DIR:\$PATH\""
    fi
    say "Docs:  https://lesysbot.github.io"
    printf '\n'
}

# Leave a copy behind so --uninstall works with no network and no checkout.
self_copy() {
    src=$(script_dir 2>/dev/null) || return 0
    [ -f "$src/install.sh" ] || return 0
    [ "$src/install.sh" = "$INSTALL_DIR/install.sh" ] && return 0
    cp "$src/install.sh" "$INSTALL_DIR/install.sh" 2>/dev/null || return 0
    chmod +x "$INSTALL_DIR/install.sh" 2>/dev/null || true
}

# ── uninstall ─────────────────────────────────────────────────────────────────
# The service lives at a fixed per-user path — --prefix and LESYSBOT_HOME do not
# move it — so a sandboxed test run would otherwise uninstall the real machine's
# service. Same guard `lesysbot setup` honours.
remove_service() {
    if [ -n "${LESYSBOT_SKIP_SERVICE:-}" ]; then
        note "Leaving the background service alone (LESYSBOT_SKIP_SERVICE set)."
        return 0
    fi
    case "$(uname -s)" in
        Darwin)
            plist="$HOME/Library/LaunchAgents/com.lesysbot.lesysbot.plist"
            if [ -f "$plist" ]; then
                launchctl unload "$plist" >/dev/null 2>&1 || true
                rm -f "$plist"
                ok "LaunchAgent removed"
            fi
            ;;
        Linux)
            unit="$HOME/.config/systemd/user/lesysbot.service"
            if [ -f "$unit" ]; then
                systemctl --user stop lesysbot >/dev/null 2>&1 || true
                systemctl --user disable lesysbot >/dev/null 2>&1 || true
                rm -f "$unit"
                systemctl --user daemon-reload >/dev/null 2>&1 || true
                ok "systemd user unit removed"
            fi
            ;;
    esac
}

strip_path_block() {
    for rc in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshenv"; do
        [ -f "$rc" ] || continue
        grep -qF "$MARK_BEGIN" "$rc" 2>/dev/null || continue
        tmp="$rc.lesysbot.tmp"
        sed "/^$MARK_BEGIN\$/,/^$MARK_END\$/d" "$rc" > "$tmp" && mv "$tmp" "$rc"
        ok "PATH entry removed from ${rc##*/}"
    done
}

do_uninstall() {
    data_dir="${LESYSBOT_HOME:-$HOME/.lesysbot}"
    printf '\n'
    say "${BOLD}Uninstalling LeSysBot${NC}"
    rule
    remove_service

    stack="$data_dir/dashboard/scripts/stop.sh"
    [ -x "$stack" ] && sh "$stack" >/dev/null 2>&1 || true

    rm -f "$BIN_DIR/lesysbot"
    rm -rf "$INSTALL_DIR"
    ok "Command and environment removed"
    strip_path_block

    if [ -n "$PURGE" ]; then
        rm -rf "$data_dir"
        ok "$data_dir deleted"
    else
        printf '\n'
        say "Your settings, tools and logs are still in $data_dir"
        say "Delete them too with:  --purge"
    fi
    printf '\n'
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    if [ -n "$UNINSTALL" ]; then
        do_uninstall
        exit 0
    fi

    if on_path; then PATH_WAS_SET="yes"; else PATH_WAS_SET="no"; fi

    printf '\n  %sLeSysBot installer%s\n' "$BOLD" "$NC"
    rule
    printf '\n'

    # A checkout installs and seeds from the tree being edited; a piped run has
    # no checkout and takes the release archive, which is the normal path.
    #
    # Written out rather than chained through `dirname "$(script_dir)"`: when
    # script_dir fails (which is exactly what a `curl … | sh` run does), that
    # collapses to `dirname ""`, which is `.` — so a piped install started from
    # inside *any* directory containing a pyproject.toml would install that
    # project instead of LeSysBot.
    REPO_DIR=""
    if here=$(script_dir 2>/dev/null); then
        candidate=$(dirname "$here")
        [ -f "$candidate/pyproject.toml" ] && REPO_DIR="$candidate"
    fi

    resolve_latest_release
    ensure_python
    make_venv
    install_package
    link_shim
    self_copy
    ensure_path
    ensure_ollama
    pull_model
    run_setup
    epilogue
}

main "$@"
