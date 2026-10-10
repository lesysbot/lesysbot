"""NVIDIA GPU detail — utilization, memory, temperature, power.

Static in shape (the nvidia_gpu_exporter metric names don't vary), but shipped
as ``dashboard.py`` rather than a frozen ``dashboard.json`` so the panel list
can grow per-host later without changing the package format.

The gating lives in the README's ``prerequisites:``, not here: on a machine
where the NVIDIA metric isn't being scraped LeSysBot **withholds** this
dashboard with a reason rather than provisioning four blank panels, and it
appears on its own once the exporter starts.
"""
from __future__ import annotations

_PANELS = [
    ("GPU utilization", "nvidia_smi_utilization_gpu_ratio * 100", "percent", 100),
    ("GPU memory used", "nvidia_smi_memory_used_bytes", "bytes", None),
    ("GPU temperature", "nvidia_smi_temperature_gpu", "celsius", None),
    ("Power draw", "nvidia_smi_power_draw_watts", "watts", None),
]


def build(host: str, caps: set[str], ctx: dict) -> dict:
    """The Grafana model for this host. Signature is the dashboard-package API."""
    panels = []
    for index, (title, expr, unit, maximum) in enumerate(_PANELS):
        defaults: dict = {"unit": unit, "min": 0}
        if maximum is not None:
            defaults["max"] = maximum
        panels.append({
            "id": index,
            "type": "timeseries",
            "title": title,
            "gridPos": {"h": 9, "w": 12, "x": (index % 2) * 12, "y": (index // 2) * 9},
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "targets": [{"expr": expr, "legendFormat": "{{uuid}}", "refId": "A"}],
        })
    return {
        "uid": "lesysbot-gpu-detail",
        "title": "GPU Detail",
        "description": f"NVIDIA GPU utilization, memory, thermals and power ({host}).",
        "tags": ["lesysbot"],
        "timezone": "browser",
        "refresh": "30s",
        "time": {"from": "now-3h", "to": "now"},
        "schemaVersion": 39,
        "panels": panels,
    }
