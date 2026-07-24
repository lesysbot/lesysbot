"""Gather a snapshot of LeSysBot's state — shared by the CLI status screen
(bare ``lesysbot``) and the management UI's ``/api/status`` endpoint."""
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
_GRAFANA_CANDIDATES = ["http://localhost:3000", "http://localhost:3001",
                       "http://127.0.0.1:3000", "http://127.0.0.1:3001"]


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

    Honours `LESYSBOT_GRAFANA_URL` if set (shown even if it's momentarily down);
    otherwise probes the usual local ports and returns the first that actually
    answers as Grafana — so it finds a stack bumped to 3001 and skips whatever
    else is on 3000. Returns `{"url", "version"}` or None.
    """
    import os

    env = os.environ.get("LESYSBOT_GRAFANA_URL", "").rstrip("/")
    if env:
        return {"url": env, "version": _grafana_version(env)}
    for url in _GRAFANA_CANDIDATES:
        ver = _grafana_version(url)
        if ver is not None:
            return {"url": url, "version": ver}
    return None


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
    if check_health:
        try:
            health = await probe_health(settings.llm)
        except Exception as e:
            health = {"ok": False, "error": str(e)}
        grafana = detect_grafana()

    daemon = None
    if provider != "cli":
        try:
            from lesysbot.core.singleton import holder_pid, instance_key
            pid = holder_pid(instance_key(settings))
            daemon = {"provider": provider, "pid": pid, "running": bool(pid)}
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
        "daemon": daemon,
        "webui_port": settings.webui.port,
    }
