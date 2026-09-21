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
