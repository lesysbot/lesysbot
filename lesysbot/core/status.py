"""Gather a snapshot of LeSysBot's state — shared by the CLI status screen
(bare ``lesysbot``) and the control panel's ``/api/status`` endpoint."""
from __future__ import annotations

from typing import Any

from lesysbot.core.config import Settings
from lesysbot.core.paths import user_dir


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("lesysbot")
    except Exception:
        return "0.1.0"


# Where the bundled monitoring stack's Grafana usually listens. Probed only to
# show a link on the status screen; 3001 is the fallback when 3000 is taken.
_GRAFANA_PORTS = ["3000", "3001"]
_GRAFANA_HOSTS = ["localhost", "127.0.0.1"]


def _monitoring_port() -> str | None:
    """The Grafana host port the bundled stack is configured for, if any.

    ``monitoring/.env`` is the one place a user moves Grafana off 3000 when
    something else already owns that port, so it's the best hint about where
    Grafana actually is — better than the fixed guesses below.
    """
    from lesysbot.core.paths import parse_env_file, user_dir

    port = parse_env_file(user_dir() / "monitoring" / ".env").get("GRAFANA_PORT", "")
    return port if port.isdigit() else None


def grafana_candidates() -> list[str]:
    """Local URLs to probe for Grafana, configured port first."""
    ports = list(_GRAFANA_PORTS)
    configured = _monitoring_port()
    if configured:
        ports.insert(0, configured)
    out: list[str] = []
    for port in ports:
        for host in _GRAFANA_HOSTS:
            url = f"http://{host}:{port}"
            if url not in out:
                out.append(url)
    return out


def _grafana_version(url: str, timeout: float = 1.0):
    """Return Grafana's version if `url` answers as Grafana, else None."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=timeout) as r:
            d = json.load(r)
        if isinstance(d, dict) and ("database" in d or "version" in d):
            return d.get("version") or "?"
    except Exception:
        return None
    return None


def detect_grafana():
    """Find the monitoring stack's Grafana so the status screen can link to it.

    `LESYSBOT_GRAFANA_URL` wins, but it is **verified** rather than trusted: a
    saved URL goes stale as soon as the stack moves off 3000 (because something
    else owns that port), and reporting "Grafana on 3000" when 3000 is somebody
    else's service is worse than not looking. So an override that doesn't answer
    as Grafana falls through to probing the usual local ports, and the first URL
    that really answers wins. Only when nothing answers do we fall back to
    reporting the override as **unreachable** (it may just be momentarily down),
    which callers must not present as a working dashboard.
    Returns `{"url", "version", "reachable"}` or None.
    """
    import os

    env = os.environ.get("LESYSBOT_GRAFANA_URL", "").rstrip("/")
    if env:
        ver = _grafana_version(env)
        if ver is not None:
            return {"url": env, "version": ver, "reachable": True}
    for url in grafana_candidates():
        ver = _grafana_version(url)
        if ver is not None:
            return {"url": url, "version": ver, "reachable": True}
    return {"url": env, "version": None, "reachable": False} if env else None


def webui_url(settings: Settings, port: int | None = None) -> str:
    """Where the control panel lives (loopback only — the host isn't settable)."""
    return f"http://127.0.0.1:{port or settings.webui.port}"


def detect_webui(settings: Settings, port: int | None = None,
                 timeout: float = 0.7) -> dict:
    """Is the always-on control panel answering? ``{url, port, running}``.

    The panel is served by the background service (``lesysbot run``), so this is
    how the CLI status screen — a short-lived, read-only process — reports it.
    ``/api/ping`` identifies *our* server, so something else squatting on the
    port reads as "not running" instead of being advertised as the panel.
    """
    import json
    import urllib.request

    port = port or settings.webui.port
    url = webui_url(settings, port)
    running = False
    try:
        with urllib.request.urlopen(url + "/api/ping", timeout=timeout) as r:
            data = json.load(r)
        running = isinstance(data, dict) and data.get("service") == "lesysbot-webui"
    except Exception:
        running = False
    return {"url": url, "port": port, "running": running}


async def probe_health(llm_config) -> dict:
    """Run the LLM health probe and close the client in the same event loop, so a
    one-shot ``asyncio.run(probe_health(...))`` doesn't leak an httpx client that
    later gets finalized on a closed loop."""
    from lesysbot.llm.client import LLMClient

    client = LLMClient(llm_config)
    try:
        return await client.health()
    finally:
        await client.aclose()


def build_registry(settings: Settings):
    """A ToolRegistry over the resolved tools dir, with the disabled-set loaded.

    This imports the tool code, exactly as the bot and the `lesysbot tools` CLI
    do, so tool listings/toggles match what the bot sees.
    """
    from lesysbot.mcp.registry import ToolRegistry

    reg = ToolRegistry()
    if settings.mcp.state_file:
        reg.set_state_path(settings.mcp.state_file)
    reg.load_directory(settings.mcp.tools_dir)
    if settings.mcp.state_file:
        reg.load_state()
    return reg


async def gather_status(
    settings: Settings, registry=None, *, check_health: bool = True
) -> dict[str, Any]:
    """A dict describing the current backend, tools, and (optionally) LLM health."""
    provider = settings.messaging.provider

    reg, reg_err = registry, None
    if reg is None:
        try:
            reg = build_registry(settings)
        except Exception as e:  # a broken tool must not crash the status screen
            reg_err = str(e)

    rows = reg.tool_status() if reg is not None else []
    enabled = sum(1 for t in rows if t["enabled"])
    unavailable = sum(1 for t in rows if not t["available"])

    health = None
    grafana = None
    webui = None
    if check_health:
        try:
            health = await probe_health(settings.llm)
        except Exception as e:
            health = {"ok": False, "error": str(e)}
        grafana = detect_grafana()
        webui = detect_webui(settings)

    # The service runs for every provider now — it hosts the control panel even
    # when there's no remote chat to poll — so its state is always reported.
    try:
        from lesysbot.core.singleton import holder_pid, instance_key, is_running
        key = instance_key(settings)
        running = is_running(key)
        daemon = {"provider": provider, "pid": holder_pid(key) if running else None,
                  "running": running}
    except Exception:
        daemon = None

    return {
        "version": _version(),
        "provider": provider,
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "config_path": str(settings.config_path) if settings.config_path else None,
        "home": str(user_dir()),
        "tools_dir": str(settings.mcp.tools_dir),
        "tools": {"total": len(rows), "enabled": enabled, "unavailable": unavailable},
        "tool_rows": rows,
        "registry_error": reg_err,
        "health": health,
        "grafana": grafana,
        "webui": webui,
        "daemon": daemon,
        "webui_port": settings.webui.port,
    }
