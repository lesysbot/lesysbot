"""Tests for the control-panel server and the shared status snapshot."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lesysbot.core.config import Settings
from lesysbot.core.status import build_registry, gather_status
from lesysbot.webui.server import _Handler, _Server


def _make_settings(tmp_path) -> Settings:
    tools = tmp_path / "tools"
    (tools / "hello").mkdir(parents=True)
    (tools / "hello" / "README.md").write_text("---\nname: hello\n---\n")
    (tools / "hello" / "tool.py").write_text(
        "from lesysbot.mcp import tool\n"
        "@tool(description='say hi')\n"
        "async def hello() -> str:\n    return 'hi'\n"
    )
    return Settings(
        messaging={"provider": "cli"},
        llm={"base_url": "http://127.0.0.1:1/v1", "model": "m"},  # refused fast → health ok:False
        mcp={"tools_dir": str(tools), "state_file": str(tmp_path / "state.json"),
             "lock_file": str(tmp_path / "lock.json")},
        logging={"file": None, "trace_file": None},
    )


class _Live:
    def __init__(self, settings):
        self.registry = build_registry(settings)
        self.srv = _Server(("127.0.0.1", 0), _Handler, settings, self.registry)
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()

    def req(self, method, path, body=None, host=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method,
                                   headers={"Content-Type": "application/json"})
        if host:
            r.add_header("Host", host)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


class _Foreign(ThreadingHTTPServer):
    """Some *other* service holding the panel's port — must not be mistaken for it."""

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    def __init__(self):
        super().__init__(("127.0.0.1", 0), self._H)
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()


@pytest.fixture
def live(tmp_path, monkeypatch):
    # Hermetic: config saves resolve to user_dir()/config.yaml when no config file
    # is loaded, so pin the home to tmp — never touch the real ~/.lesysbot.
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    s = _Live(_make_settings(tmp_path))
    yield s
    s.stop()


def test_serves_html_and_tools(live):
    code, body = live.req("GET", "/")
    assert code == 200 and b"<title>LeSysBot" in body
    code, body = live.req("GET", "/api/tools")
    assert code == 200
    assert "hello" in [t["name"] for t in json.loads(body)["tools"]]


def test_toggle_persists_to_state_file(live, tmp_path):
    code, body = live.req("POST", "/api/tools/toggle", {"name": "hello", "enabled": False})
    assert code == 200 and json.loads(body)["ok"] is True
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["disabled"] == ["hello"]
    # unknown tool → 404
    code, _ = live.req("POST", "/api/tools/toggle", {"name": "nope", "enabled": False})
    assert code == 404


def test_config_get_and_validation(live):
    code, body = live.req("GET", "/api/config")
    assert code == 200 and "provider" in json.loads(body)["yaml"]
    # invalid config is rejected before writing
    code, body = live.req("POST", "/api/config", {"yaml": "llm:\n  max_tokens: not_a_number\n"})
    assert code == 400 and "Invalid config" in json.loads(body)["error"]
    # malformed YAML is rejected too
    code, body = live.req("POST", "/api/config", {"yaml": "llm: [unclosed\n"})
    assert code == 400


def test_config_save_roundtrip(live):
    _, body = live.req("GET", "/api/config")
    text = json.loads(body)["yaml"].replace("model: m", "model: changed")
    code, body = live.req("POST", "/api/config", {"yaml": text})
    assert code == 200 and json.loads(body)["ok"] is True
    _, body = live.req("GET", "/api/config")
    assert "model: changed" in json.loads(body)["yaml"]


def test_rejects_forged_host(live):
    code, body = live.req("GET", "/api/status", host="evil.example.com")
    assert code == 403
    # a loopback Host is fine
    code, _ = live.req("GET", "/api/tools", host="localhost:1234")
    assert code == 200


def test_cli_dispatch_decision():
    """Bare `lesysbot` is the read-only status view — it starts nothing. Only
    `run` (the service) and an explicit `--provider` run a long-lived process."""
    from argparse import Namespace

    from lesysbot.__main__ import _runs_the_bot

    assert _runs_the_bot("run", Namespace(provider=None)) is True
    assert _runs_the_bot(None, Namespace(provider="cli")) is True   # foreground chat
    assert _runs_the_bot(None, Namespace(provider=None)) is False   # bare → status only
    assert _runs_the_bot("manage", Namespace(provider=None)) is False


def test_ping_identifies_the_panel(live):
    code, body = live.req("GET", "/api/ping")
    assert code == 200 and json.loads(body)["service"] == "lesysbot-webui"


def test_detect_webui_finds_a_running_panel(live):
    """The status screen's liveness probe: our panel answers, a stranger on the
    same port doesn't count, and a dead port reads as offline."""
    from lesysbot.core.status import detect_webui

    settings = live.srv.settings
    got = detect_webui(settings, port=live.port)
    assert got == {"url": f"http://127.0.0.1:{live.port}", "port": live.port, "running": True}

    # something else on the port → not our panel
    other = _Foreign()
    try:
        assert detect_webui(settings, port=other.port)["running"] is False
    finally:
        other.stop()
    # nothing listening at all
    assert detect_webui(settings, port=other.port)["running"] is False


def test_serve_background_binds_once(tmp_path, monkeypatch):
    """The service's panel: a daemon thread on the configured port, and a second
    copy backs off (None) instead of quietly serving somewhere else."""
    import socket

    from lesysbot.webui.server import serve_background

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    settings = _make_settings(tmp_path)
    with socket.socket() as s:            # borrow a free port number
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings.webui.port = port

    ui = serve_background(settings)
    assert ui is not None
    try:
        assert ui.url == f"http://127.0.0.1:{port}"
        assert ui.thread.is_alive()
        with urllib.request.urlopen(ui.url + "/api/ping", timeout=5) as r:
            assert json.load(r)["ok"] is True
        assert serve_background(settings) is None      # port already ours
    finally:
        ui.stop()


async def test_probe_health_always_closes_client(monkeypatch):
    """The client must be closed in-loop (else 'Event loop is closed' at GC)."""
    from lesysbot.core import status

    closed = {"n": 0}

    class FakeClient:
        def __init__(self, _cfg):
            pass

        async def health(self):
            raise RuntimeError("backend down")

        async def aclose(self):
            closed["n"] += 1

    monkeypatch.setattr("lesysbot.llm.client.LLMClient", FakeClient)
    with pytest.raises(RuntimeError):
        await status.probe_health(object())
    assert closed["n"] == 1  # closed even though health() raised


def test_detect_grafana(monkeypatch, tmp_path):
    from lesysbot.core import status

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))   # no bundled .env to read
    # explicit env override wins when Grafana really answers there
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf:3000")
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: "11.5.1" if "gf" in u else None)
    assert status.detect_grafana() == {
        "url": "http://gf:3000", "version": "11.5.1", "reachable": True}
    # a *stale* override (stack moved off 3000) must not outrank the real Grafana
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: "11.5.1" if "3001" in u else None)
    assert status.detect_grafana()["url"] == "http://localhost:3001"
    # no env: skip whatever's on 3000 (not Grafana), pick the real one on 3001
    monkeypatch.delenv("LESYSBOT_GRAFANA_URL", raising=False)
    assert status.detect_grafana()["url"] == "http://localhost:3001"
    # nothing answers → no link
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: None)
    assert status.detect_grafana() is None
    # …but a configured URL is still reported, flagged unreachable
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf:3000")
    assert status.detect_grafana() == {
        "url": "http://gf:3000", "version": None, "reachable": False}


def test_grafana_candidates_prefer_the_configured_port(monkeypatch, tmp_path):
    """A stack moved off 3000 (GRAFANA_PORT in monitoring/.env) is probed first."""
    from lesysbot.core import status

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    (tmp_path / "monitoring").mkdir()
    (tmp_path / "monitoring" / ".env").write_text("GRAFANA_PORT=3007\n", encoding="utf-8")
    cands = status.grafana_candidates()
    assert cands[:2] == ["http://localhost:3007", "http://127.0.0.1:3007"]
    assert "http://localhost:3000" in cands and len(cands) == len(set(cands))


async def test_gather_status_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    settings = _make_settings(tmp_path)
    st = await gather_status(settings, check_health=False)
    assert st["provider"] == "cli"
    assert st["tools"]["total"] >= 1 and st["tools"]["enabled"] >= 1
    assert st["webui_port"] == settings.webui.port
    # probes are skipped with check_health=False…
    assert st["health"] is None and st["grafana"] is None and st["webui"] is None
    # …but the service is reported for every provider, cli included, since it is
    # what serves the control panel (nothing running here → stopped).
    assert st["daemon"] == {"provider": "cli", "pid": None, "running": False}
