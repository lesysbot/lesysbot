"""Tests for the management UI server and the shared status snapshot."""
import json
import threading
import urllib.error
import urllib.request

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


def test_cli_dispatch_decision(monkeypatch):
    """Bare `lesysbot` opens the UI only in a TTY; the service (non-TTY) and
    `run`/`--provider` always run the bot."""
    import types
    from argparse import Namespace

    from lesysbot.__main__ import _wants_management_ui

    assert _wants_management_ui("manage", Namespace(provider=None)) is True
    assert _wants_management_ui("run", Namespace(provider=None)) is False
    assert _wants_management_ui(None, Namespace(provider="cli")) is False  # explicit provider

    # bare + interactive terminal → management UI
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("sys.stdout", types.SimpleNamespace(isatty=lambda: True))
    assert _wants_management_ui(None, Namespace(provider=None)) is True
    # bare + no terminal (the background service) → run the bot, unchanged
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: False))
    assert _wants_management_ui(None, Namespace(provider=None)) is False


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


def test_detect_grafana(monkeypatch):
    from lesysbot.core import status

    # explicit env override wins
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf:3000")
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: "11.5.1" if "gf" in u else None)
    assert status.detect_grafana() == {"url": "http://gf:3000", "version": "11.5.1"}
    # no env: skip whatever's on 3000 (not Grafana), pick the real one on 3001
    monkeypatch.delenv("LESYSBOT_GRAFANA_URL", raising=False)
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: "11.5.1" if "3001" in u else None)
    assert status.detect_grafana()["url"] == "http://localhost:3001"
    # nothing answers → no link
    monkeypatch.setattr(status, "_grafana_version", lambda u, **k: None)
    assert status.detect_grafana() is None


async def test_gather_status_shape(tmp_path):
    settings = _make_settings(tmp_path)
    st = await gather_status(settings, check_health=False)
    assert st["provider"] == "cli"
    assert st["tools"]["total"] >= 1 and st["tools"]["enabled"] >= 1
    assert st["webui_port"] == settings.webui.port
    assert st["health"] is None and st["grafana"] is None  # check_health=False
