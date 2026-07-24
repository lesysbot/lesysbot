"""Tests for the bundled share-dashboard tool (network fully mocked)."""
import importlib.util
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "share-dashboard" / "tool.py"


def load(monkeypatch, home):
    """Load the tool module fresh, pointed at a temp LESYSBOT_HOME."""
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    spec = importlib.util.spec_from_file_location("share_dash_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_grafana(_cfg, path):
    if "/api/dashboard/snapshots" in path:      # Grafana's snapshot registry
        return [{"key": "KEY123", "name": "System Overview — snap", "external": True,
                 "externalUrl": "https://snapshots.raintank.io/dashboard/snapshot/KEY123",
                 "expires": "2099-01-01T00:00:00Z"}]
    if "/api/search" in path:
        return [{"uid": "lesysbot-node"}]
    if "/api/dashboards/uid/" in path:
        return {"dashboard": {"title": "System Overview", "panels": [
            {"type": "row", "title": "section"},
            {"type": "timeseries", "title": "CPU", "targets": [
                {"expr": 'cpu{instance=~"$instance"}', "legendFormat": "{{mode}}", "refId": "A"}]},
        ]}}
    raise AssertionError(f"unexpected grafana path {path}")


async def test_share_bakes_data_records_and_lists(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)
    posted = {}
    monkeypatch.setattr(m, "_grafana", _fake_grafana)
    monkeypatch.setattr(m, "_resolve_grafana", lambda cfg: "http://localhost:3001")
    monkeypatch.setattr(m, "_query_range",
                        lambda cfg, expr, s, e, step: [{"metric": {"mode": "user"},
                                                        "values": [[s, "1"], [e, "2"]]}])

    def fake_post(url, body, headers=None, timeout=45):
        posted["url"], posted["body"] = url, body
        return {"key": "KEY123", "url": "https://snapshots.raintank.io/dashboard/snapshot/KEY123",
                "deleteUrl": "http://localhost:3001/api/snapshots-delete/DEL123",
                "deleteKey": "DEL123"}
    monkeypatch.setattr(m, "_post", fake_post)

    async def _ready(*a, **k):
        return True
    monkeypatch.setattr(m, "_confirm_available", _ready)   # don't hit the network

    out = await m.share_dashboard(expiration="1d")
    assert "KEY123" in out and "expires in 1d" in out

    # published through Grafana (which relays to raintank), external flag set
    assert posted["url"] == "http://localhost:3001/api/snapshots"
    assert posted["body"]["external"] is True
    # data baked into the panel as a modern queryType:snapshot target
    panel = [p for p in posted["body"]["dashboard"]["panels"] if p.get("type") == "timeseries"][0]
    target = panel["targets"][0]
    assert target["queryType"] == "snapshot"
    entry = target["snapshot"][0]
    assert entry["data"]["values"][1] == [1.0, 2.0]
    assert entry["schema"]["fields"][1]["config"]["displayNameFromDS"] == "user"  # {{mode}} resolved
    assert posted["body"]["expires"] == 86400
    assert "$instance" not in str(posted["body"])            # template tokens substituted

    listed = await m.list_snapshots()
    assert "KEY123" in listed and "expires in" in listed


async def test_delete_by_number_goes_through_grafana(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_resolve_grafana", lambda cfg: "http://localhost:3001")
    state = {"snaps": [{"key": "K", "name": "snap", "external": True,
                        "externalUrl": "https://snapshots.raintank.io/dashboard/snapshot/K",
                        "expires": "2099-01-01T00:00:00Z"}]}

    def fake_grafana(_cfg, path):
        assert "/api/dashboard/snapshots" in path
        return state["snaps"]
    monkeypatch.setattr(m, "_grafana", fake_grafana)

    hit = []
    def fake_delete(url, headers=None, timeout=20):
        hit.append(url)
        state["snaps"] = []              # gone from Grafana after delete
        return {"message": "Snapshot deleted"}
    monkeypatch.setattr(m, "_delete", fake_delete)

    out = await m.delete_snapshot(which="1")
    assert "Snapshot deleted." in out and "CDN caches" in out
    assert hit and hit[0].endswith("/api/snapshots/K")
    assert "No dashboard snapshots" in await m.list_snapshots()


async def test_unknown_expiration_is_rejected(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)
    out = await m.share_dashboard(expiration="2y")
    assert "Unknown expiration" in out


async def test_orphan_is_listed_and_deleted_via_raintank(tmp_path, monkeypatch):
    """A snapshot Grafana has pruned but we still track (unexpired) is surfaced as
    an orphan and deleted straight from raintank via its stored deleteKey."""
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_resolve_grafana", lambda cfg: "http://localhost:3001")
    monkeypatch.setattr(m, "_grafana", lambda cfg, path: [])   # Grafana forgot everything
    m._save([{"key": "ORPH", "name": "orphan",
              "url": "https://snapshots.raintank.io/dashboard/snapshot/ORPH",
              "deleteKey": "DKEY", "expires_at": int(time.time()) + 3600}])

    listed = await m.list_snapshots()
    assert "ORPH" in listed and "raintank" in listed          # surfaced as an orphan

    hits = []
    monkeypatch.setattr(m, "_get", lambda url, *a, **k: hits.append(url) or {"message": "deleted"})
    out = await m.delete_snapshot(which="1")
    assert "Snapshot deleted." in out and "CDN caches" in out
    assert any(u.endswith("/api/snapshots-delete/DKEY") for u in hits)   # raintank deleteKey used
    assert "No dashboard snapshots" in await m.list_snapshots()          # local record cleared


async def test_local_fallback_prunes_expired_when_grafana_down(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_resolve_grafana", lambda cfg: "http://localhost:3001")

    def down(_cfg, _path):
        raise m._StackDown("connection refused")
    monkeypatch.setattr(m, "_grafana", down)
    m._save([{"key": "old", "name": "old", "url": "u1", "expires_at": int(time.time()) - 5},
             {"key": "keep", "name": "forever", "url": "u2", "expires_at": None}])
    out = await m.list_snapshots()
    assert "Grafana unreachable" in out and "forever" in out and "old" not in out


def test_grafana_autodetect(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)
    # explicit env override always wins, no probing
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf.example:9999")
    monkeypatch.setattr(m, "_is_grafana", lambda url, **k: pytest.fail("should not probe"))
    assert m._resolve_grafana(m._cfg()) == "http://gf.example:9999"
    # no override: skip the impostor on 3000, pick the real Grafana on 3001
    monkeypatch.delenv("LESYSBOT_GRAFANA_URL", raising=False)
    monkeypatch.setattr(m, "_is_grafana", lambda url, **k: "3001" in url)
    assert m._resolve_grafana(m._cfg()) == "http://localhost:3001"
    # nothing answers: fall back to the default for a sensible error
    monkeypatch.setattr(m, "_is_grafana", lambda url, **k: False)
    assert m._resolve_grafana(m._cfg()) == "http://localhost:3000"


async def test_stack_down_is_friendly(tmp_path, monkeypatch):
    m = load(monkeypatch, tmp_path)

    def boom(_cfg, _path):
        raise m._StackDown("connection refused")
    monkeypatch.setattr(m, "_grafana", boom)
    out = await m.share_dashboard(expiration="1h")
    assert "monitoring stack" in out.lower() or "reach grafana" in out.lower()
