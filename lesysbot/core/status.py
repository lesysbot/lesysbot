"""Gather a snapshot of LeSysBot's state — shared by the CLI status screen
(bare ``lesysbot``) and the management panel's ``/api/status`` endpoint."""
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


# Grafana/Prometheus discovery lives in core/grafana.py — one parser and one
# probe, rather than the three and two this module used to be part of.
# Deliberately re-exported by name only. An alias for `api_health` used to live
# here too, which made `monkeypatch.setattr(status, "_grafana_version", ...)`
# look like it worked while the real call went through core.grafana untouched —
# a patched-out probe that silently hit the developer's live Grafana instead.
from lesysbot.core.grafana import detect_grafana, grafana_candidates  # noqa: E402,F401

__all__ = ["detect_grafana", "grafana_candidates", "detect_panel", "panel_url",
           "gather_status", "build_registry", "probe_health", "PANEL_SERVICE_ID"]


def panel_url(settings: Settings, port: int | None = None) -> str:
    """Where the management panel lives (loopback only — the host isn't settable)."""
    return f"http://127.0.0.1:{port or settings.management.port}"


# What `/api/ping` answers with, so a stranger holding the port reads as
# "not running" rather than being advertised as the panel.
PANEL_SERVICE_ID = "lesysbot-management"


def detect_panel(settings: Settings, port: int | None = None,
                 timeout: float = 0.7) -> dict:
    """Is the always-on management panel answering? ``{url, port, running}``.

    The panel is served by the background service (``lesysbot run``), so this is
    how the CLI status screen — a short-lived, read-only process — reports it.
    ``/api/ping`` identifies *our* server, so something else squatting on the
    port reads as "not running" instead of being advertised as the panel.
    """
    import json
    import urllib.request

    port = port or settings.management.port
    url = panel_url(settings, port)
    running = False
    try:
        with urllib.request.urlopen(url + "/api/ping", timeout=timeout) as r:
            data = json.load(r)
        running = isinstance(data, dict) and data.get("service") == PANEL_SERVICE_ID
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
    panel = None
    if check_health:
        try:
            health = await probe_health(settings.llm)
        except Exception as e:
            health = {"ok": False, "error": str(e)}
        grafana = detect_grafana()
        panel = detect_panel(settings)

    # The service runs for every provider now — it hosts the management panel even
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
        "panel": panel,
        "daemon": daemon,
        "panel_port": settings.management.port,
    }
