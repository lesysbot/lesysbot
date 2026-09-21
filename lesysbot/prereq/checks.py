"""The individual prerequisite checkers.

Each takes a :class:`Requirement` and answers it against this machine, returning
a :class:`Result` that always carries a reason and — when it can — a fix. Every
fix is unprivileged or, where no unprivileged route exists, is stated as text
for the user to run themselves. Nothing here ever executes ``sudo``.

Checkers must be cheap and total: they run on every status screen and before
every install, so a missing binary, an unreachable port or a wedged daemon has
to come back as a negative result rather than an exception or a 30-second hang.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
from typing import Callable

from lesysbot.prereq.report import Requirement, Result

# Short probe timeouts: this runs on the status screen, so a wedged daemon must
# read as "not answering" quickly rather than stalling the whole command.
NET_TIMEOUT = 0.7
CMD_TIMEOUT = 5.0

_OS_LABELS = {"linux": "Linux"}

# Well-known services a package may depend on, and where they usually listen.
_SERVICE_PORTS = {
    "prometheus": 9090,
    "grafana": 3000,
    "ollama": 11434,
}
_SERVICE_FIX = {
    "prometheus": "start the dashboard stack: `lesysbot dashboard start`",
    "grafana": "start the dashboard stack: `lesysbot dashboard start`",
    "ollama": "start Ollama — https://ollama.com/download",
}


def _ok(req, detail="") -> Result:
    return Result(req, True, detail)


def _no(req, detail, fix="", auto=False) -> Result:
    return Result(req, False, detail, fix, auto)


# -- os / arch -----------------------------------------------------------------

# What a README writes to mean "no OS constraint". `platforms: all` is the
# convention across the bundled packages, so reading it as a literal OS name
# would report every cross-platform tool as broken.
ANY_PLATFORM = {"all", "any", "*"}


def check_os(req: Requirement) -> Result:
    from lesysbot.core.host import current_os

    here = current_os()
    wanted = [p.strip().lower() for p in req.value.replace(",", " ").split() if p.strip()]
    if not wanted or ANY_PLATFORM & set(wanted) or here in wanted:
        return _ok(req, _OS_LABELS.get(here, here))
    runs_on = ", ".join(_OS_LABELS.get(w, w) for w in wanted)
    return _no(req, f"this is {_OS_LABELS.get(here, here)}; needs {runs_on}")


def check_arch(req: Requirement) -> Result:
    from lesysbot.core.host import current_arch, normalize_arch

    here = current_arch()
    want = normalize_arch(req.value)
    if not want or here == want:
        return _ok(req, here)
    return _no(req, f"this machine is {here}, needs {want}")


def _version_tuple(text: str) -> tuple[int, ...]:
    """``"14.5.1"`` → ``(14, 5, 1)``; non-numeric parts stop the parse.

    Deliberately not `packaging.version` — OS versions are dotted integers in
    practice, and this must not add a dependency to a module that runs on every
    status screen.
    """
    parts: list[int] = []
    for chunk in text.strip().split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check_os_version(req: Requirement) -> Result:
    """Compare this machine's OS version against ``>=X.Y`` (or a bare ``X.Y``).

    Bare values mean *at least*, because that is what a manifest almost always
    intends: a dashboard needing Ubuntu 24.04 works on 25.04 too. Pinning an
    exact release is rare enough to be worth spelling out as ``==``.

    An undeterminable version **passes**. Refusing to install because we could
    not read /etc/os-release would turn a detection gap into a hard failure on
    the user's machine, which is the wrong way round.
    """
    from lesysbot.core.host import os_version

    here = os_version()
    if not here:
        return _ok(req, "OS version unknown — not enforced")

    raw = req.value.strip()
    for prefix in (">=", "==", ">"):
        if raw.startswith(prefix):
            operator, wanted = prefix, raw[len(prefix):].strip()
            break
    else:
        operator, wanted = ">=", raw

    if not wanted:
        return _ok(req, here)

    mine, theirs = _version_tuple(here), _version_tuple(wanted)
    if not theirs:
        return _ok(req, here)

    if operator == "==":
        # Compare only as precisely as the manifest asked: `== 14` means any
        # 14.x, not "14 and no patch component".
        satisfied = mine[:len(theirs)] == theirs
    elif operator == ">":
        satisfied = mine > theirs
    else:
        satisfied = mine >= theirs

    if satisfied:
        return _ok(req, here)
    return _no(req, f"this is version {here}, needs {operator} {wanted}")


# -- binaries and Python -------------------------------------------------------

def check_binary(req: Requirement) -> Result:
    found = shutil.which(req.value)
    if found:
        return _ok(req, found)
    return _no(req, f"'{req.value}' is not on PATH", _binary_fix(req.value))


# Binaries whose package name isn't their command name, or that don't come from
# a package manager at all. `nvidia-smi` is the motivating case: it ships *with*
# the NVIDIA driver, so `brew install nvidia-smi` is not a command that exists.
_KNOWN_BINARY_FIXES = {
    "nvidia-smi": "install the NVIDIA driver — https://www.nvidia.com/download/index.aspx",
    "docker": "install Docker Engine — https://docs.docker.com/engine/install/",
    "ollama": "install Ollama — https://ollama.com/download",
    "nslookup": "part of bind-utils / dnsutils",
    "traceroute": "part of inetutils (or the traceroute package)",
}


def _binary_fix(name: str) -> str:
    """How to get a missing binary. Never `sudo`, and never a guessed package name.

    Suggesting `brew install <command>` is right often enough to be tempting and
    wrong often enough to mislead — package names routinely differ from the
    command they install. So an exact command is only offered where it is known
    to be correct; otherwise this names the binary and leaves the choice of
    package manager to the person who knows their machine.
    """
    known = _KNOWN_BINARY_FIXES.get(name)
    if known:
        return known
    return f"install '{name}' with your package manager"


def check_python(req: Requirement) -> Result:
    """An importable module. Distinct from `pip`: this asks whether it's *there*."""
    module = req.value.split()[0].split("==")[0].split(">=")[0].strip()
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        return _ok(req, module)
    return _no(req, f"module '{module}' is not importable",
               f"pip install {module}", auto=True)


def check_pip(req: Requirement) -> Result:
    """A pip requirement LeSysBot installs itself — the one auto-fixable kind."""
    result = check_python(Requirement("python", req.value, req.optional))
    if result.satisfied:
        return _ok(req, result.detail)
    return _no(req, result.detail, f"pip install {req.value}", auto=True)


# -- gpu -----------------------------------------------------------------------

def check_gpu(req: Requirement) -> Result:
    from lesysbot.prereq import gpu

    info = gpu.detect(req.value or "nvidia")
    if info.usable:
        return _ok(req, info.detail)
    return _no(req, info.detail, info.fix)


# -- docker --------------------------------------------------------------------

def _docker_step(args: list[str]) -> bool:
    try:
        return subprocess.run(args, capture_output=True,
                              timeout=CMD_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_docker(req: Requirement) -> Result:
    """Installed, Compose v2 present, and the daemon actually reachable.

    Split into three because the fix differs at each step, and "Docker is
    broken" is not an actionable thing to tell somebody.
    """
    if shutil.which("docker") is None:
        return _no(req, "docker is not installed",
                   "install Docker Engine — https://docs.docker.com/engine/install/")
    if not _docker_step(["docker", "compose", "version"]):
        return _no(req, "Docker Compose v2 is missing",
                   "install the compose plugin (docker-compose-plugin)")
    if not _docker_step(["docker", "info"]):
        return _no(req, "the Docker daemon is not reachable",
                   "start Docker, and add yourself to the `docker` group so it "
                   "works without sudo: `sudo usermod -aG docker $USER` then log out")
    return _ok(req, "installed, Compose v2, daemon up")


# -- network services ----------------------------------------------------------

def _listening(host: str, port: int, timeout: float = NET_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_service(req: Requirement) -> Result:
    """A named service, or a literal ``host:port``, answering on loopback."""
    name = req.value.strip()
    host, port = "127.0.0.1", _SERVICE_PORTS.get(name.lower())

    if port is None:
        if ":" not in name:
            return _no(req, f"unknown service {name!r}")
        host, _, raw = name.rpartition(":")
        host = host or "127.0.0.1"
        if not raw.isdigit():
            return _no(req, f"'{name}' is not a host:port")
        port = int(raw)
    else:
        port = _configured_port(name.lower(), port)

    if _listening(host, port):
        return _ok(req, f"{host}:{port}")
    return _no(req, f"nothing listening on {host}:{port}",
               _SERVICE_FIX.get(name.lower(), ""))


# Both stack services move when their default port is taken, and the stack's
# `.env` is where that is recorded. Consulting it for Grafana but not Prometheus
# produced a false "Prometheus is not running" on any machine that had moved it
# — which would withhold a perfectly good dashboard. Whatever is in `_ENV_PORTS`
# is asked; anything else keeps its well-known default.
_ENV_PORTS = {"prometheus": "PROM_PORT", "grafana": "GRAFANA_PORT"}


def _configured_port(service: str, default: int) -> int:
    key = _ENV_PORTS.get(service)
    if key is None:
        return default
    from lesysbot.core.grafana import stack_env

    value = stack_env().get(key, "")
    return int(value) if value.isdigit() else default


def check_port(req: Requirement) -> Result:
    """A port that must be *free* — an exporter can't bind one already in use."""
    raw = req.value.strip()
    if not raw.isdigit():
        return _no(req, f"'{raw}' is not a port number")
    port = int(raw)
    if not _listening("127.0.0.1", port):
        return _ok(req, f"{port} is free")
    return _no(req, f"{port} is already in use{_port_holder(port)}",
               "stop whatever holds it, or change the port in the stack's .env")


def _port_holder(port: int) -> str:
    """Name the process holding a port, when the OS will tell us cheaply."""
    if shutil.which("lsof") is None:
        return ""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=CMD_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = out.splitlines()[1:]
    return f" ({lines[0].split()[0]})" if lines else ""


# -- prometheus metrics --------------------------------------------------------

def check_metric(req: Requirement) -> Result:
    """Is a metric actually being scraped right now?

    This is the check that makes an installed dashboard trustworthy: a panel
    querying a series nobody collects renders empty, and an empty panel is
    indistinguishable from a broken one.
    """
    import json
    import urllib.parse
    import urllib.request

    name = req.value.strip()
    base = f"http://127.0.0.1:{_configured_prometheus_port()}"
    if not _listening("127.0.0.1", _configured_prometheus_port()):
        return _no(req, "Prometheus is not running",
                   "start the dashboard stack: `lesysbot dashboard start`")
    url = f"{base}/api/v1/query?" + urllib.parse.urlencode({"query": name})
    try:
        with urllib.request.urlopen(url, timeout=2.0) as r:
            data = json.load(r)
    except Exception as e:
        return _no(req, f"could not query Prometheus ({e})")
    results = (data.get("data") or {}).get("result") or []
    if results:
        return _ok(req, f"{len(results)} series")
    return _no(req, f"'{name}' is not being scraped",
               "install the exporter that provides it, or check "
               "prometheus/prometheus.yml")


def _configured_prometheus_port(default: int = 9090) -> int:
    return _configured_port("prometheus", default)


# -- registry ------------------------------------------------------------------

CHECKERS: dict[str, Callable[[Requirement], Result]] = {
    "os": check_os,
    "platform": check_os,          # `platforms:` in frontmatter maps here
    "arch": check_arch,
    "os_version": check_os_version,
    "os-version": check_os_version,
    "binary": check_binary,
    "requires": check_binary,      # `requires:` in frontmatter maps here
    "python": check_python,
    "pip": check_pip,
    "gpu": check_gpu,
    "docker": check_docker,
    "service": check_service,
    "port": check_port,
    "metric": check_metric,
}


def check(req: Requirement) -> Result:
    """Run one requirement's checker.

    An unknown type is reported as satisfied-with-a-note rather than failing:
    manifests are written by other people against other versions, and a package
    declaring something this LeSysBot has never heard of should still install.
    """
    checker = CHECKERS.get(req.type)
    if checker is None:
        return Result(req, True, f"unknown requirement type {req.type!r} — not checked")
    try:
        return checker(req)
    except Exception as e:                      # a checker must never take a command down
        return Result(req, True, f"check failed ({e}) — not enforced")


def check_all(requirements: list[Requirement]) -> list[Result]:
    return [check(r) for r in requirements]


def is_ci() -> bool:
    """True in CI, where hardware probes are meaningless."""
    return bool(os.environ.get("CI"))
