"""One place that knows where Grafana and Prometheus are, and how to ask them.

There were three separate parsers for ``GRAFANA_PORT`` and two ``/api/health``
probes — in ``core/status``, ``setup/apply`` and the ``share-dashboard`` tool —
which had drifted to the point of disagreeing about the fallback (``None`` vs
``"3000"``). Anything new that talked to Grafana would have made it a fourth.

The governing rule, which the duplicates already half-implemented and which is
stated once here: **a configured URL is verified, never trusted.** A saved
address goes stale the moment the stack moves off its port — because something
else took it — and advertising whatever now answers there as "your Grafana" is
worse than admitting we can't find it.

``tools/share-dashboard/`` deliberately keeps its own copy. Tool packages are
copy-paste self-contained by design, so it must work when lifted out of this
repo entirely.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_GRAFANA_PORT = "3000"
DEFAULT_PROMETHEUS_PORT = "9090"

# Where to look when the stack's own .env doesn't say. 3001 is the usual second
# choice when something else already owns 3000.
_GRAFANA_PORTS = ("3000", "3001")
_HOSTS = ("localhost", "127.0.0.1")

_PROBE_TIMEOUT = 1.0


@dataclass(frozen=True)
class Endpoint:
    url: str
    reachable: bool
    version: str | None = None


def stack_env(base=None) -> dict[str, str]:
    """The dashboard stack's ``.env`` — the one place ports are configured."""
    from lesysbot.core.paths import dashboard_dir

    return env_of_stack(dashboard_dir(base))


def env_of_stack(stack_dir) -> dict[str, str]:
    """The ``.env`` of an explicitly given stack directory.

    Two entry points because callers legitimately hold different things: the
    wizard has the *stack* directory in hand, while the bot has the data
    directory and must resolve the stack from it. Both land on this one parser
    rather than growing a second.
    """
    from lesysbot.core.paths import parse_env_file

    return parse_env_file(stack_dir / ".env")


def _port(env: dict[str, str], key: str, default: str) -> str:
    value = env.get(key, "")
    return value if value.isdigit() else default


def grafana_port(base=None) -> str:
    """Grafana's host port from the stack's ``.env``, else 3000."""
    return _port(stack_env(base), "GRAFANA_PORT", DEFAULT_GRAFANA_PORT)


def grafana_port_of_stack(stack_dir) -> str:
    """Grafana's port, for a caller that already knows the stack directory."""
    return _port(env_of_stack(stack_dir), "GRAFANA_PORT", DEFAULT_GRAFANA_PORT)


def prometheus_port(base=None) -> str:
    return _port(stack_env(base), "PROM_PORT", DEFAULT_PROMETHEUS_PORT)


def grafana_local_url(base=None) -> str:
    return f"http://localhost:{grafana_port(base)}"


def prometheus_url(base=None) -> str:
    return f"http://127.0.0.1:{prometheus_port(base)}"


def grafana_candidates(base=None) -> list[str]:
    """Local URLs to probe for Grafana, the configured port first."""
    ports = [grafana_port(base), *(p for p in _GRAFANA_PORTS)]
    out: list[str] = []
    for port in dict.fromkeys(ports):
        for host in _HOSTS:
            url = f"http://{host}:{port}"
            if url not in out:
                out.append(url)
    return out


# --- choosing a port ---------------------------------------------------------
#
# Grafana binds 127.0.0.1:<GRAFANA_PORT> on the host network, so when anything
# else already listens there it crash-loops with "address already in use" and
# the dashboard silently never comes up. 3000 is the default port of half the
# web dev servers on earth, so this is the common case, not an edge one.

#: How far past the configured port to look for a free one.
PORT_SEARCH_SPAN = 100

_OUR_GRAFANA = "lesysbot-grafana"


def port_in_use(port: int | str, host: str = "127.0.0.1") -> bool:
    """Would binding *host*:*port* fail? Asks the kernel, not a guess.

    A bind test rather than a connect: it answers exactly the question Grafana's
    own ``listen`` will ask, so a listener on ``0.0.0.0`` counts as taken too.
    ``SO_REUSEADDR`` matches Go's listener, so a socket lingering in TIME_WAIT
    isn't mistaken for one.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, int(port)))
        except OSError:
            return True
    return False


def our_grafana_port(runner=None) -> str | None:
    """The port the bundled Grafana container is *healthily* serving, else None.

    A busy port is only a conflict when the holder isn't us: re-running
    ``start.sh`` on a working stack must not "fix" it onto another port. A
    container that is restarting is crash-looping — typically on exactly this
    conflict — so it holds nothing.
    """
    import subprocess

    runner = runner or subprocess.run
    try:
        r = runner(
            ["docker", "inspect", "-f",
             "{{.State.Running}} {{.State.Restarting}}"
             "{{range .Config.Env}} {{.}}{{end}}", _OUR_GRAFANA],
            capture_output=True, text=True,
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    fields = (r.stdout or "").split()
    if fields[:2] != ["true", "false"]:
        return None
    for field in fields[2:]:
        if field.startswith("GF_SERVER_HTTP_PORT="):
            return field.split("=", 1)[1]
    return None


def grafana_port_conflict(port: int | str, runner=None) -> bool:
    """Is *port* held by something other than our own running Grafana?"""
    if not port_in_use(port):
        return False
    return our_grafana_port(runner) != str(port)


def next_free_port(start: int | str, avoid: tuple = (), span: int = PORT_SEARCH_SPAN) -> str | None:
    """The first port after *start* that nothing listens on, skipping *avoid*."""
    skip = {str(a) for a in avoid}
    for candidate in range(int(start) + 1, int(start) + 1 + span):
        if str(candidate) not in skip and not port_in_use(candidate):
            return str(candidate)
    return None


def set_stack_env(stack_dir, key: str, value: str) -> None:
    """Set one ``KEY=value`` line in the stack's ``.env``, keeping the rest.

    The stack's ``.env`` is user-owned (seeded once, never overwritten), so this
    edits the one line in place rather than rewriting the file.
    """
    env = stack_dir / ".env"
    try:
        lines = env.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    out, seen = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            if not seen:
                out.append(f"{key}={value}")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"{key}={value}")
    env.write_text("\n".join(out) + "\n", encoding="utf-8")


def sync_saved_url(stack_dir, grafana_env) -> str | None:
    """Point a saved *local* ``LESYSBOT_GRAFANA_URL`` at the stack's current port.

    ``start.sh`` may move Grafana off a taken port; the URL the wizard saved in
    ``grafana.env`` would then name the old one. Detection would still find
    Grafana (a saved URL is verified, never trusted), but the file shouldn't
    keep advertising the program that took the port. A non-local URL is a
    deliberate remote Grafana and is left alone. Returns the new URL when the
    file was changed.
    """
    from urllib.parse import urlsplit

    try:
        lines = grafana_env.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    want = f"http://localhost:{grafana_port_of_stack(stack_dir)}"
    out, changed = [], False
    for line in lines:
        if line.startswith("LESYSBOT_GRAFANA_URL="):
            url = line.split("=", 1)[1].strip()
            if urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1") and url.rstrip("/") != want:
                line, changed = f"LESYSBOT_GRAFANA_URL={want}", True
        out.append(line)
    if not changed:
        return None
    grafana_env.write_text("\n".join(out) + "\n", encoding="utf-8")
    return want


def api_health(url: str, timeout: float = _PROBE_TIMEOUT) -> str | None:
    """Grafana's version if *url* answers as Grafana, else None.

    Identity, not liveness: ``/api/health`` returning JSON with a ``database`` or
    ``version`` key is what distinguishes Grafana from any other service that
    happens to hold the port.
    """
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=timeout) as r:
            data = json.load(r)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if isinstance(data, dict) and ("database" in data or "version" in data):
        return data.get("version") or "?"
    return None


def reset_admin_password(password: str, runner=None) -> bool:
    """Set the admin password inside our running Grafana container.

    ``GF_SECURITY_ADMIN_PASSWORD`` is read only on the first boot of an empty
    ``grafana-data`` volume, so on any existing install a password written to
    ``.env`` never reaches Grafana. ``grafana cli admin reset-admin-password``
    writes it to the database itself. The password goes over stdin, not argv,
    so it never shows up in ``ps``. Needs Docker access, not root.
    """
    import subprocess

    runner = runner or subprocess.run
    try:
        r = runner(
            ["docker", "exec", "-i", _OUR_GRAFANA, "grafana", "cli", "admin",
             "reset-admin-password", "--password-from-stdin"],
            input=password, capture_output=True, text=True,
        )
    except OSError:
        return False
    return r.returncode == 0


def detect_grafana(base=None) -> dict | None:
    """Find Grafana. ``{url, version, reachable}``, or None when unconfigured.

    ``LESYSBOT_GRAFANA_URL`` wins *if it answers as Grafana*; otherwise the local
    candidates are probed and the first real one wins. Only when nothing answers
    is an unreachable override reported — which callers must not render as a
    working link.
    """
    override = os.environ.get("LESYSBOT_GRAFANA_URL", "").rstrip("/")
    if override:
        version = api_health(override)
        if version is not None:
            return {"url": override, "version": version, "reachable": True}
    for url in grafana_candidates(base):
        version = api_health(url)
        if version is not None:
            return {"url": url, "version": version, "reachable": True}
    return {"url": override, "version": None, "reachable": False} if override else None


#: The dashboard a bare "open Grafana" link should land on.
HOME_DASHBOARD = "system-overview"


def dashboard_uid(path) -> str | None:
    """The ``uid`` of a provisioned dashboard JSON file, or None if unreadable."""
    try:
        uid = json.loads(path.read_text(encoding="utf-8")).get("uid")
    except (OSError, ValueError, AttributeError):
        return None
    return uid if isinstance(uid, str) and uid else None


def provisioned_uids(base=None) -> dict[str, str]:
    """``{dashboard name: uid}`` for every dashboard JSON Grafana provisions.

    The copy ``start.sh`` wrote (``generated/``) wins over the stack's static
    portable one of the same name, since it is what Grafana is showing.
    """
    from lesysbot.core.paths import dashboard_dir, generated_dashboards_dir

    out: dict[str, str] = {}
    for directory in (dashboard_dir(base) / "grafana" / "dashboards",
                      generated_dashboards_dir(base)):
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                if uid := dashboard_uid(path):
                    out[path.stem] = uid
    return out


def dashboard_link(grafana_url: str, uid: str) -> str:
    """A link that opens one dashboard, not Grafana's home page."""
    return f"{grafana_url.rstrip('/')}/d/{uid}"


def home_dashboard_url(grafana_url: str, base=None) -> str | None:
    """Where "open the dashboard" should go: System Overview, else any provisioned one."""
    uids = provisioned_uids(base)
    uid = uids.get(HOME_DASHBOARD) or next(iter(uids.values()), None)
    return dashboard_link(grafana_url, uid) if uid else None


def query(metric: str, base=None, timeout: float = 2.0) -> list | None:
    """Run an instant PromQL query. None when Prometheus can't be reached.

    Distinguishing "no series" (``[]``) from "couldn't ask" (None) is the whole
    point: a dashboard prerequisite must not read a down Prometheus as proof
    that a metric is missing.
    """
    import urllib.parse

    url = f"{prometheus_url(base)}/api/v1/query?" + urllib.parse.urlencode({"query": metric})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return (data.get("data") or {}).get("result") or []
