#!/usr/bin/env bash
# Install and run the whole dashboard stack natively on macOS, via Homebrew.
#
#   ./scripts/install-macos.sh          # install what's missing, configure, start
#   ./scripts/install-macos.sh down     # stop the services (nothing uninstalled)
#   ./scripts/install-macos.sh status   # what's running, and is Grafana answering
#
# No Docker Desktop. Three brew formulae run under `brew services` (so they come
# back after a reboot):
#
#   grafana        :GRAFANA_PORT  — dashboard UI, provisioned from this folder
#   prometheus     :PROM_PORT     — scrapes and stores the time series
#   node_exporter  :9100          — CPU, memory, disk, per-interface network
#
# It adapts to the Mac it finds. Apple Silicon and Intel expose different
# readings, and a dashboard panel that can never fill is indistinguishable from a
# broken one — so rather than provisioning one dashboard for every Mac, it
# detects the hardware and generates the matching cut:
#
#   Apple Silicon vs Intel  — Intel adds node_exporter's thermal-throttling
#                             panels (that collector does nothing on M-series)
#   NVIDIA GPU present?     — the NVIDIA row and its scrape job are included
#                             only when nvidia-smi can actually answer them
#   die-temperature helper  — offered, never required; see section 1a
#
# Ports/credentials come from dashboard/.env — the same file the Docker stack
# reads, so there is one place to change them. Everything binds 127.0.0.1 only.
#
# Environment:
#   LESYSBOT_TEMP_HELPER=macmon|smctemp|none   answer the section-1a prompt
#                                              up front (unattended installs)
#
# On Linux use ./scripts/start.sh instead (Docker, host network). This script is
# also the macOS path `lesysbot setup` runs for you.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

FORMULAE=(grafana prometheus node_exporter)
NATIVE="$ROOT/native"                     # generated config, git-ignored
TEXTFILE_DIR="$NATIVE/textfile"           # node_exporter textfile collector drop
AGENT_LABEL="com.lesysbot.macos-metrics"  # launchd job refreshing that drop
AGENT_PLIST="$HOME/Library/LaunchAgents/$AGENT_LABEL.plist"
MARK_BEGIN=";;; BEGIN LeSysBot — managed block, edits below are overwritten ;;;"
MARK_END=";;; END LeSysBot ;;;"

log()  { printf '\033[1;34m[dashboard]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[dashboard]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dashboard]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[dashboard]\033[0m %s\n' "$*" >&2; exit 1; }

# ── settings (dashboard/.env, same file the Docker stack reads) ──────────────
env_get() { # $1 key  $2 default
  local v=""
  [ -f "$ROOT/.env" ] && v="$(sed -n "s/^$1=//p" "$ROOT/.env" | tail -1 | tr -d '\r')"
  printf '%s' "${v:-$2}"
}

GRAFANA_PORT="$(env_get GRAFANA_PORT 3000)"
PROM_PORT="$(env_get PROM_PORT 9090)"
PROM_RETENTION="$(env_get PROM_RETENTION 15d)"
ADMIN_USER="$(env_get GRAFANA_ADMIN_USER admin)"
ADMIN_PASSWORD="$(env_get GRAFANA_ADMIN_PASSWORD admin)"
NODE_PORT=9100
NVIDIA_PORT=9835

# ── what kind of Mac is this? ────────────────────────────────────────────────
# Three facts change what gets installed and which dashboard is provisioned, so
# they're settled once, up front, and echoed back by `status`. Getting them
# wrong is what leaves a dashboard full of panels the machine can never fill.
case "$(uname -m)" in
  arm64) MAC_ARCH=arm64;  MAC_KIND="Apple Silicon" ;;
  *)     MAC_ARCH=x86_64; MAC_KIND="Intel" ;;
esac
CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
[ -n "$CHIP" ] || CHIP="$MAC_KIND Mac"

# nvidia_gpu_exporter works by shelling out to nvidia-smi, so nvidia-smi is the
# test for whether GPU metrics are *possible* — a card with no driver cannot be
# scraped by anything. NVIDIA stopped shipping macOS drivers after Mojave, so
# this is false on essentially every Mac, and the NVIDIA dashboard row is then
# left out entirely instead of being provisioned permanently empty.
has_nvidia() { command -v nvidia-smi >/dev/null 2>&1; }

# Only consulted to explain an absent row (system_profiler takes a second or two,
# so it is never on the fast path).
nvidia_hardware_present() {
  system_profiler SPDisplaysDataType 2>/dev/null | grep -qi nvidia
}

# Die temperatures need a third-party helper — see section 1a. macmon is
# `arch: :arm64`, so Intel Macs only ever get the smctemp suggestion.
temp_helper() { # -> prints the installed helper's name, if any
  for h in smctemp macmon; do
    if command -v "$h" >/dev/null 2>&1; then printf '%s' "$h"; return 0; fi
  done
  return 1
}
if [ "$MAC_ARCH" = arm64 ]; then
  TEMP_HELPER_TAP=macmon
else
  TEMP_HELPER_TAP=narugit/tap/smctemp
fi

# The --have list for gen-dashboards.py. Same vocabulary as CAPABILITIES["macos"]
# there and as start.sh's detect_capabilities_macos, and the two must not drift:
# a capability this doesn't claim is a dashboard row that silently goes missing,
# and one it claims wrongly is a row that can never fill.

# Ask the collector whether a GPU die temperature actually comes out, rather
# than inferring it from the chip or from "a helper is installed". Neither
# inference works: on an M1 macmon installs fine, fills the CPU tile, and still
# reports 0 for the GPU (its IOReport temperature channels read 0 there), while
# smctemp 0.7.0 cannot read that sensor either. Running the real collector is
# the only answer that cannot be wrong, and it is the same probe-don't-guess
# rule start.ps1 follows for windows_exporter's thermal zones.
# `${VAR:-}` because this is also reached with the script *sourced* (the test
# harness runs under `set -u`, and PYTHON is assigned past the sourcing guard).
has_gpu_die_temp() {
  [ -n "${PYTHON:-}" ] || return 1
  [ -f "${HERE:-}/macos-metrics.py" ] || return 1
  "$PYTHON" "${HERE}/macos-metrics.py" --stdout 2>/dev/null \
    | grep -q '^macos_gpu_temperature_celsius '
}

dashboard_caps() {
  local caps=""
  [ "$MAC_ARCH" = arm64 ] || caps="intel"
  if has_nvidia; then caps="${caps:+$caps,}nvidia"; fi
  if has_gpu_die_temp; then caps="${caps:+$caps,}gpu_die_temp"; fi
  printf '%s' "$caps"
}

# Sourcing this file defines the helpers above and stops here, so the capability
# detection can be driven without Homebrew, without macOS and without installing
# anything (see tests/test_install_macos.py). Same arrangement as start.sh.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
  return 0
fi

# ── preflight ────────────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || die "This script is macOS-only. On Linux run ./scripts/start.sh"

if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew is required and isn't installed. Install it with:

    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"

  then run this script again."
fi
BREW_PREFIX="$(brew --prefix)"
GRAFANA_INI="$BREW_PREFIX/etc/grafana/grafana.ini"

# Pin an interpreter that outlives shells and shims: launchd has its own minimal
# PATH, and whatever `command -v python3` resolves to today may be a virtualenv
# or conda env that gets deleted. Brew's python ships with the rest of this
# stack; /usr/bin/python3 is macOS'. Both the metrics collector and the dashboard
# generator are stdlib-only, so any of these works.
PYTHON=""
for candidate in "$BREW_PREFIX/bin/python3" /usr/bin/python3 "$(command -v python3 || true)"; do
  if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done

# ── verbs that don't install anything ────────────────────────────────────────
cmd_down() {
  for f in "${FORMULAE[@]}"; do
    brew services stop "$f" >/dev/null 2>&1 && log "stopped $f" || true
  done
  if launchctl bootout "gui/$UID/$AGENT_LABEL" >/dev/null 2>&1; then
    log "stopped the GPU/temperature collector"
  fi
  # Only ever running on a Mac with an NVIDIA driver, but stopping it is free:
  # run-exporters.sh no-ops when there is no pid file.
  [ -f "$HERE/run-exporters.sh" ] && bash "$HERE/run-exporters.sh" stop >/dev/null 2>&1 || true
  ok "dashboard stack stopped. Start it again with:  $0"
}

cmd_status() {
  # Lead with what this host was set up *as*: nearly every "panel X is empty"
  # question is answered by one of these three lines rather than by a service
  # being down.
  log "$CHIP ($MAC_KIND)"
  if has_nvidia; then
    log "NVIDIA: nvidia-smi found — the NVIDIA GPU row is provisioned"
  else
    log "NVIDIA: none — that dashboard row is deliberately not provisioned"
  fi
  local helper=""
  if helper="$(temp_helper)"; then
    log "die temperatures: $helper installed — CPU/GPU temperature tiles work"
  else
    log "die temperatures: no helper installed — those two tiles stay empty"
    log "  fix: brew install $TEMP_HELPER_TAP"
  fi
  echo
  brew services list | awk 'NR==1 || /^(grafana|prometheus|node_exporter)[[:space:]]/'
  echo
  if curl -fsS --max-time 3 "http://127.0.0.1:$GRAFANA_PORT/api/health" >/dev/null 2>&1; then
    ok "Grafana is answering on http://localhost:$GRAFANA_PORT"
  else
    warn "Grafana is not answering on http://localhost:$GRAFANA_PORT"
  fi
  if curl -fsS --max-time 3 "http://127.0.0.1:$PROM_PORT/-/ready" >/dev/null 2>&1; then
    ok "Prometheus is ready on http://localhost:$PROM_PORT"
  else
    warn "Prometheus is not ready on http://localhost:$PROM_PORT"
  fi
  # A stale .prom file keeps being served after the collector dies, so report the
  # age of the last sample rather than merely that the file exists.
  if [ -f "$TEXTFILE_DIR/macos.prom" ]; then
    local age; age=$(( $(date +%s) - $(stat -f %m "$TEXTFILE_DIR/macos.prom") ))
    if [ "$age" -lt 60 ]; then
      ok "GPU/temperature collector ran ${age}s ago"
    else
      warn "GPU/temperature collector last ran ${age}s ago — check:"
      warn "  launchctl print gui/$UID/$AGENT_LABEL"
    fi
  else
    warn "GPU/temperature collector has never run (no $TEXTFILE_DIR/macos.prom)"
  fi
}

case "${1:-up}" in
  down)   cmd_down;   exit 0 ;;
  status) cmd_status; exit 0 ;;
  up)     ;;
  *) die "usage: $0 [up|down|status]" ;;
esac

# The Docker stack serves the same ports; running both means whichever grabbed
# the port first wins and the other crash-loops. Say so instead of racing it.
if command -v docker >/dev/null 2>&1 &&
   docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^lesysbot-'; then
  die "The bundled Docker stack is already running and owns these ports.
  Stop it first:  $HERE/start.sh down
  (or keep using it — it serves the same dashboard.)"
fi

# ── 1. install the formulae ──────────────────────────────────────────────────
for f in "${FORMULAE[@]}"; do
  if brew list --formula --versions "$f" >/dev/null 2>&1; then
    log "$f already installed"
  else
    # Braces are load-bearing: bash 3.2 (macOS' /bin/bash) reads the ellipsis'
    # UTF-8 bytes as part of the variable name, so "$f…" is an unbound "f…".
    log "installing ${f}…"
    brew install "$f" || die "brew install $f failed — see the output above."
  fi
done

# ── 1a. optional: a helper for CPU/GPU die temperature ───────────────────────
# Apple publishes die temperature only through IOReport (a private framework) or
# root-only powermetrics, and nothing here ever asks for sudo — so those two
# tiles need one of two small third-party tools. Neither may become a hard
# dependency: both are personal taps rather than homebrew-core, and both fail on
# ordinary machines (brew refuses them on an outdated Xcode; smctemp compiles
# from source so it also wants the Command Line Tools; macmon ships a prebuilt
# binary but is arm64-only). So: offer, default to no, and never fail the
# install over it — everything else on the dashboard works without them.
#
# LESYSBOT_TEMP_HELPER=macmon|smctemp|none picks without asking, which is also
# what happens when there is no terminal to ask at (a piped/unattended install).
install_temp_helper() { # $1 = macmon|smctemp
  local tap
  case "$1" in
    macmon)  tap=macmon ;;
    smctemp) tap=narugit/tap/smctemp ;;
    *) return 1 ;;
  esac
  log "installing ${1}…"
  if brew install "$tap"; then
    ok "$1 installed — CPU/GPU die temperature appears within 15s"
  else
    warn "brew install $tap failed — this is optional, so the install continues."
    warn "It usually means Xcode / Command Line Tools are missing or out of date:"
    warn "  xcode-select --install"
    warn "The dashboard works without it; only the two die-temperature tiles stay empty."
  fi
}

ask_temp_helper() { # -> prints macmon|smctemp|none
  local reply=""
  {
    echo
    echo "  CPU and GPU die temperature need a small helper on macOS."
    echo "  Without one those two tiles stay empty; every other panel works."
    echo
    if [ "$MAC_ARCH" = arm64 ]; then
      echo "    1) macmon    prebuilt binary, nothing to compile   (recommended)"
      echo "    2) smctemp   builds from source, needs Xcode CLT"
    else
      echo "    1) smctemp   builds from source, needs Xcode CLT"
      echo "                 (macmon is Apple Silicon only, so it isn't offered here)"
    fi
    echo "    n) skip      — install either one later, any time"
    echo
  } >&2
  printf '  Install a temperature helper? [1/%sn] (default: n) ' \
    "$( [ "$MAC_ARCH" = arm64 ] && echo "2/" )" >&2
  read -r reply || reply=n
  case "$reply" in
    1) [ "$MAC_ARCH" = arm64 ] && echo macmon || echo smctemp ;;
    2) [ "$MAC_ARCH" = arm64 ] && echo smctemp || echo none ;;
    *) echo none ;;
  esac
}

if existing_helper="$(temp_helper)"; then
  log "die temperature: $existing_helper already installed"
else
  choice="${LESYSBOT_TEMP_HELPER:-}"
  case "$choice" in
    macmon|smctemp|none) ;;
    "") if [ -t 0 ]; then choice="$(ask_temp_helper)"; else choice=none; fi ;;
    *)  warn "ignoring LESYSBOT_TEMP_HELPER=$choice (expected macmon, smctemp or none)"
        choice=none ;;
  esac
  if [ "$choice" = none ]; then
    log "skipping the die-temperature helper — CPU/GPU temperature tiles stay empty"
    log "  add one later:  brew install $TEMP_HELPER_TAP"
  elif [ "$choice" = macmon ] && [ "$MAC_ARCH" != arm64 ]; then
    warn "macmon is Apple Silicon only — installing smctemp instead."
    install_temp_helper smctemp
  else
    install_temp_helper "$choice"
  fi
fi

# ── 1b. free our own ports, then check nothing else owns them ────────────────
# Stopping first is what makes the check meaningful on a re-run: otherwise our
# own running services look like a conflict. A busy port is worth catching here
# because the failure is otherwise silent — brew services just parks the service
# in `error` state and the dashboard comes up with no data behind it.
for f in "${FORMULAE[@]}"; do
  brew services stop "$f" >/dev/null 2>&1 || true
done

port_owner() { # $1 = port -> "COMMAND (pid N)" when something is listening
  # The trailing `|| true` is required, not defensive: `lsof` exits 1 when the
  # port is free, and with `set -o pipefail` that failure propagates out of the
  # command substitution and kills the script under `set -e` — before any caller
  # can act on the (perfectly normal) empty result.
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null |
    awk 'NR == 2 {gsub(/\\x20/, " ", $1); print $1 " (pid " $2 ")"}' || true
}

check_port() { # $1 = port  $2 = what wants it  $3 = the .env key to change
  # An explicit `if`, not `[ -z "$owner" ] && return 0`: under `set -e` that
  # compound exits the *function* with status 1 on a busy port, killing the
  # script before it ever reaches the message explaining why.
  local owner; owner="$(port_owner "$1")"
  if [ -n "$owner" ]; then
    die "Port $1 ($2) is already in use by $owner.
  Pick another port in $ROOT/.env — set ${3}=<free port> — then re-run this script.
  ($2 binds 127.0.0.1 only, so this is a clash on your own machine.)"
  fi
}

check_port "$GRAFANA_PORT" Grafana       GRAFANA_PORT
check_port "$PROM_PORT"    Prometheus    PROM_PORT
if [ -n "$(port_owner "$NODE_PORT")" ]; then
  # node_exporter's port isn't configurable from .env (the dashboards and the
  # generated scrape config both assume 9100), so this one is a warning: the
  # host-metrics panels will be empty until whatever holds it lets go.
  warn "Port $NODE_PORT (node_exporter) is in use by $(port_owner "$NODE_PORT") —"
  warn "CPU/memory/disk/network panels will stay empty until that port is free."
fi

# ── 2. generate the native config tree ───────────────────────────────────────
# Grafana's provisioning files can't use ${PROM_URL} here (no compose to inject
# it). Dashboards are provisioned from grafana/dashboards/generated — the same
# directory the two compose stacks mount and that `lesysbot dashboard render`
# writes to, so all three launch paths serve the same set and an installed
# dashboard package shows up however the stack happens to be running.
#
# It has to be that *subdirectory* and not grafana/dashboards itself: the
# provider loads every JSON it finds, and the committed portable cuts live one
# level up — pointing at them would provision the Windows dashboard on a Mac,
# permanently empty. One file lands there, named and uid'd the same whichever
# route wrote it, so the machine has one dashboard at /d/lesysbot.
GENERATED="$ROOT/grafana/dashboards/generated"
rm -rf "$NATIVE"
mkdir -p "$NATIVE/provisioning/datasources" "$NATIVE/provisioning/dashboards" \
         "$GENERATED" "$TEXTFILE_DIR"

cat > "$NATIVE/provisioning/datasources/datasource.yml" <<EOF
# Generated by scripts/install-macos.sh — edit that script, not this file.
# Same contract as the Docker stack's provisioning/datasources/datasource.yml:
# the fixed uid \`prometheus\` is what every bundled dashboard binds its panels to.
apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:$PROM_PORT
    isDefault: true
    editable: false
    jsonData:
      timeInterval: 15s
EOF

cat > "$NATIVE/provisioning/dashboards/dashboards.yml" <<EOF
# Generated by scripts/install-macos.sh — edit that script, not this file.
apiVersion: 1

providers:
  - name: lesysbot
    orgId: 1
    folder: LeSysBot
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: $GENERATED
      foldersFromFilesStructure: false
EOF

# The bundled JSON is the *portable* dashboard: one file has to serve Linux and
# every Mac, so it carries panels this host can never fill (Linux hwmon CPU and
# disk sensors, and an NVIDIA row that no modern Mac can answer). Ask the
# generator for a cut that matches the hardware detected above instead — it drops
# those and adds the Intel-only throttling panels where they apply. Falling back
# to the portable file keeps the stack installable without python3.
DASHBOARD="$GENERATED/lesysbot.json"
GEN="$HERE/gen-dashboards.py"
DASH_CAPS="$(dashboard_caps)"
DASH_FLAVOUR="$MAC_KIND"
if has_nvidia; then DASH_FLAVOUR="$DASH_FLAVOUR + NVIDIA"; fi

# Never swallow the generator's stderr. This call once passed flags the generator
# had stopped accepting; argparse exited 2, the error went to /dev/null, and every
# Mac quietly got the portable dashboard instead — the exact symptom the per-host
# cut exists to prevent, reported as "why are these rows empty on my Mac".
dashboard_fallback() { # $1 = why
  cp "$ROOT/grafana/dashboards/system-overview-linux-macos.json" "$DASHBOARD"
  warn "Using the portable Linux/macOS dashboard — couldn't generate one for this host:"
  warn "  $1"
  warn "It works, but its Linux-only sensor panels stay empty on a Mac."
}

if [ -z "$PYTHON" ]; then
  dashboard_fallback "no python3 found to run $GEN"
elif [ ! -f "$GEN" ]; then
  dashboard_fallback "$GEN is missing"
elif gen_err="$("$PYTHON" "$GEN" --host macos --have "$DASH_CAPS" \
                --out "$DASHBOARD" 2>&1 >/dev/null)"; then
  log "dashboard generated for this host ($DASH_FLAVOUR) [${DASH_CAPS:-no optional capabilities}]"
  if ! has_nvidia && nvidia_hardware_present; then
    warn "An NVIDIA GPU is present but nvidia-smi isn't — NVIDIA stopped shipping"
    warn "macOS drivers after Mojave, so its metrics can't be read. The NVIDIA row"
    warn "is left out rather than provisioned permanently empty."
  fi
else
  dashboard_fallback "${gen_err:-$GEN exited non-zero}"
fi

# Prometheus scrapes the host directly here — no host.docker.internal hop.
{
  cat <<EOF
# Generated by scripts/install-macos.sh — edit that script, not this file.
# Native macOS stack: everything runs on the host, so targets are plain
# localhost (the Docker stack's prometheus/prometheus.yml uses
# host.docker.internal instead).
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:$PROM_PORT"]

  # macOS host metrics — CPU, memory, disk, filesystem, and per-device network.
  # The \`device\` label is en0 for Ethernet, en1 for Wifi.
  - job_name: node
    static_configs:
      - targets: ["localhost:$NODE_PORT"]
EOF
  # Only when nvidia-smi is here, because that is also the only case in which
  # anything will be *listening* on this port — section 4c starts the exporter.
  # A job pointing at a port nobody serves shows up as a permanently down target
  # in Prometheus, which reads as a broken stack.
  if has_nvidia; then
    cat <<EOF

  - job_name: nvidia_gpu
    static_configs:
      - targets: ["localhost:$NVIDIA_PORT"]
EOF
  fi
} > "$NATIVE/prometheus.yml"

log "wrote native config to $NATIVE"

# ── 3. point the brew services at it ─────────────────────────────────────────
# Both formulae read their flags from etc/<name>.args (see `brew info`). These
# files can't carry a comment marking them as ours — the wrapper expands the
# whole file into the command line — so we keep a `.lesysbot` stamp of what we
# last wrote. Anything that doesn't match the stamp is the user's, and gets
# backed up once instead of being overwritten silently.
write_args() { # $1 path  $2 contents
  local path="$1" body="$2" stamp="$1.lesysbot"
  if [ -s "$path" ] && [ ! -f "$path.lesysbot-backup" ] && ! cmp -s "$path" "$stamp"; then
    cp "$path" "$path.lesysbot-backup"
    warn "kept your previous $(basename "$path") as $(basename "$path").lesysbot-backup"
  fi
  printf '%s\n' "$body" > "$path"
  cp "$path" "$stamp"
}

write_args "$BREW_PREFIX/etc/prometheus.args" "--config.file=$NATIVE/prometheus.yml
--web.listen-address=127.0.0.1:$PROM_PORT
--storage.tsdb.path=$BREW_PREFIX/var/prometheus
--storage.tsdb.retention.time=$PROM_RETENTION"

write_args "$BREW_PREFIX/etc/node_exporter.args" \
  "--web.listen-address=127.0.0.1:$NODE_PORT
--collector.textfile.directory=$TEXTFILE_DIR"

# Grafana has no .args file — it's launched with a fixed --config, so we append a
# managed block to grafana.ini. Later sections/keys win, so the block overrides
# the shipped defaults without touching a line of the original.
[ -f "$GRAFANA_INI" ] || die "$GRAFANA_INI is missing — try: brew reinstall grafana"
if grep -qF "$MARK_BEGIN" "$GRAFANA_INI"; then   # drop the previous block first
  awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
    index($0, b) { skip = 1 }
    !skip        { print }
    index($0, e) { skip = 0 }
  ' "$GRAFANA_INI" > "$GRAFANA_INI.tmp" && mv "$GRAFANA_INI.tmp" "$GRAFANA_INI"
fi
# Trim trailing blank lines before appending, so the separator we add below is
# the only one — otherwise every re-run leaves one behind and the file grows.
awk 'NF {last = NR} {line[NR] = $0} END {for (i = 1; i <= last; i++) print line[i]}' \
  "$GRAFANA_INI" > "$GRAFANA_INI.tmp" && mv "$GRAFANA_INI.tmp" "$GRAFANA_INI"

cat >> "$GRAFANA_INI" <<EOF

$MARK_BEGIN
[paths]
provisioning = $NATIVE/provisioning

[server]
http_addr = 127.0.0.1
http_port = $GRAFANA_PORT

[users]
allow_sign_up = false

[analytics]
reporting_enabled = false
check_for_updates = false

[news]
news_feed_enabled = false
$MARK_END
EOF
log "configured $GRAFANA_INI"

# ── 4. admin login ───────────────────────────────────────────────────────────
# grafana.ini's [security] admin_password only applies when the database is
# created, so it can't fix an existing install — and writing the password into a
# world-readable file under $BREW_PREFIX/etc isn't something we want either. The
# CLI writes straight to the sqlite DB, so use it for both cases: create the DB
# by starting Grafana once, then set the password (server stopped, no lock
# contention). --password-from-stdin keeps it out of `ps`.
GF_HOME="$BREW_PREFIX/opt/grafana/share/grafana"
GF_DATA="$BREW_PREFIX/var/lib/grafana"

grafana_cli() {
  "$BREW_PREFIX/opt/grafana/bin/grafana" cli --config "$GRAFANA_INI" \
    --homepath "$GF_HOME" --configOverrides "cfg:default.paths.data=$GF_DATA" "$@"
}

if [ ! -f "$GF_DATA/grafana.db" ]; then
  log "first run — starting Grafana once to create its database…"
  brew services start grafana >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    [ -f "$GF_DATA/grafana.db" ] && break
    sleep 1
  done
fi

brew services stop grafana >/dev/null 2>&1 || true
if [ -f "$GF_DATA/grafana.db" ]; then
  if printf '%s' "$ADMIN_PASSWORD" | grafana_cli admin reset-admin-password \
       --password-from-stdin >/dev/null 2>&1; then
    log "admin password set from dashboard/.env"
  else
    warn "couldn't set the Grafana password automatically — log in with the"
    warn "current admin password and change it under Administration → Users."
  fi
  if [ "$ADMIN_USER" != "admin" ]; then
    warn "Grafana's built-in admin is always named 'admin'; '$ADMIN_USER' was not"
    warn "created. Either use 'admin', or add $ADMIN_USER yourself in the UI."
  fi
else
  warn "Grafana's database didn't appear — the password wasn't set."
fi

# ── 4b. macOS-only metrics (GPU + battery temperature) ───────────────────────
# node_exporter has no GPU support on macOS, and its `thermal` collector reports
# CPU throttling on Intel and nothing at all on Apple Silicon — so the GPU and
# temperature rows would stay empty. macos-metrics.py fills them from ioreg (plus
# smctemp/macmon for die temperature, if section 1a installed one) and drops a
# .prom file that node_exporter's textfile collector serves. It's a one-shot
# script, so launchd re-runs it on a timer — that also gets it back after a
# reboot, matching the brew services around it. $PYTHON was resolved at the top.
COLLECTOR="$HERE/macos-metrics.py"
if [ -f "$COLLECTOR" ] && [ -n "$PYTHON" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$AGENT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$AGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$COLLECTOR</string>
    <string>$TEXTFILE_DIR</string>
  </array>
  <key>StartInterval</key><integer>15</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$ROOT/run/macos-metrics.log</string>
</dict>
</plist>
EOF
  mkdir -p "$ROOT/run"
  launchctl bootout "gui/$UID/$AGENT_LABEL" >/dev/null 2>&1 || true
  if launchctl bootstrap "gui/$UID" "$AGENT_PLIST" >/dev/null 2>&1; then
    log "macOS GPU/temperature collector scheduled (every 15s)"
  else
    warn "Could not load the metrics collector — GPU/temperature panels stay empty."
    warn "  launchctl bootstrap gui/$UID $AGENT_PLIST"
  fi
  "$PYTHON" "$COLLECTOR" "$TEXTFILE_DIR" >/dev/null 2>&1 || true   # first sample now
elif [ -z "$PYTHON" ]; then
  warn "python3 not found — skipping the GPU/temperature collector."
fi

# ── 4c. NVIDIA GPU exporter (only when there's a driver to read) ─────────────
# Vanishingly rare on a Mac, but if nvidia-smi is here the scrape job written in
# section 2 needs something to answer it. run-exporters.sh owns downloading and
# supervising the exporter; EXPORTER_BIND keeps it on loopback like everything
# else in this stack (its own default is 0.0.0.0, for the Docker Desktop path
# where Prometheus lives in a VM and has to reach the host from outside).
if has_nvidia; then
  if [ -f "$HERE/run-exporters.sh" ] &&
     EXPORTER_BIND=127.0.0.1 bash "$HERE/run-exporters.sh" nvidia >/dev/null 2>&1; then
    log "NVIDIA GPU exporter started on 127.0.0.1:$NVIDIA_PORT"
  else
    warn "Couldn't start the NVIDIA GPU exporter — the GPU row will be empty."
    warn "  EXPORTER_BIND=127.0.0.1 bash $HERE/run-exporters.sh nvidia"
  fi
fi

# ── 5. start everything ──────────────────────────────────────────────────────
for f in "${FORMULAE[@]}"; do
  brew services restart "$f" >/dev/null 2>&1 \
    && log "started $f" \
    || warn "brew services restart $f failed — try it by hand to see why."
done

# ── 6. report ────────────────────────────────────────────────────────────────
# Check *both*: a healthy Grafana in front of a dead Prometheus renders a
# dashboard full of empty panels, which reads as "it didn't work" with nothing
# pointing at the cause.
wait_for() { # $1 = url  -> 0 when it answers within ~45s
  local i=0
  while [ "$i" -lt 45 ]; do
    curl -fsS --max-time 2 "$1" >/dev/null 2>&1 && return 0
    sleep 1
    i=$((i + 1))
  done
  return 1
}

echo
failed=""
if wait_for "http://127.0.0.1:$GRAFANA_PORT/api/health"; then
  ok "Grafana is up at http://localhost:$GRAFANA_PORT"
else
  failed=yes
  warn "Grafana didn't answer on port $GRAFANA_PORT within 45s."
  warn "  tail -n 40 $BREW_PREFIX/var/log/grafana-stderr.log"
fi
if wait_for "http://127.0.0.1:$PROM_PORT/-/ready"; then
  ok "Prometheus is up at http://localhost:$PROM_PORT"
else
  failed=yes
  warn "Prometheus didn't answer on port $PROM_PORT within 45s — the dashboard"
  warn "will render with empty panels until it does."
  warn "  tail -n 40 $BREW_PREFIX/var/log/prometheus.err.log"
fi
if [ -n "$(port_owner "$NODE_PORT")" ] &&
   ! curl -fsS --max-time 2 "http://127.0.0.1:$NODE_PORT/metrics" >/dev/null 2>&1; then
  failed=yes
  warn "Something other than node_exporter holds port $NODE_PORT — host metrics"
  warn "(CPU, memory, disk, network) will be missing."
fi

cat <<EOF

  Grafana:    http://localhost:$GRAFANA_PORT   (log in as admin with the password you set)
  Prometheus: http://localhost:$PROM_PORT/targets   (node should be 'up')

  The dashboard is under the "LeSysBot" folder in Grafana.
  Services run under \`brew services\`, so they survive a reboot.

  Stop:    $0 down
  Status:  $0 status
EOF
[ -z "$failed" ]
