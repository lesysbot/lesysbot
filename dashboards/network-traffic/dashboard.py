"""Per-interface network traffic, read from node_exporter's byte counters.

This used to branch on the host, because node_exporter and windows_exporter
name the same two counters differently. LeSysBot is Linux-only now, so the
branch is gone and only node_exporter's vocabulary is left — but the
``build(host, caps, ctx)`` signature stays, since it is the dashboard-package
API and a third-party package is free to use every bit of it.

The render context (v2) carries ``arch`` and ``os_version``; they go into the
dashboard description so a shared screenshot says which machine it came from.
"""
from __future__ import annotations

# node_exporter's per-interface byte counters, and the label it puts the
# interface name in. Loopback and virtual interfaces are filtered out — they
# add noise to a traffic graph and nobody reads a link-local bridge's rate.
_RX = "node_network_receive_bytes_total"
_TX = "node_network_transmit_bytes_total"
_FILTER = 'device!~"lo|veth.*|docker.*|br-.*"'


def _panel(panel_id: int, title: str, expr: str, y: int) -> dict:
    """One timeseries panel, bytes/second, half the dashboard width."""
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": 9, "w": 12, "x": (panel_id % 2) * 12, "y": y},
        "datasource": {"type": "prometheus", "uid": "prometheus"},
        "fieldConfig": {
            "defaults": {"unit": "Bps", "min": 0},
            "overrides": [],
        },
        "targets": [
            {"expr": expr, "legendFormat": "{{device}}", "refId": "A"},
        ],
    }


def build(host: str, caps: set[str], ctx: dict) -> dict:
    """The Grafana model for this host. Signature is the dashboard-package API."""
    selector = f"{{{_FILTER}}}"
    stamp = " ".join(
        part for part in (host, ctx.get("arch", ""), ctx.get("os_version", ""))
        if part
    )
    return {
        "uid": "lesysbot-network-traffic",
        "title": "Network Traffic",
        "description": f"Per-interface throughput. Rendered for {stamp}.",
        "tags": ["lesysbot"],
        "timezone": "browser",
        "refresh": "30s",
        "time": {"from": "now-3h", "to": "now"},
        "schemaVersion": 39,
        "panels": [
            _panel(0, "Received", f"rate({_RX}{selector}[5m])", 0),
            _panel(1, "Sent", f"rate({_TX}{selector}[5m])", 0),
        ],
    }
