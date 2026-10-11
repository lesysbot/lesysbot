"""Tests for the control-panel server and the shared status snapshot."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from lesysbot.core.config import Settings
from lesysbot.core.status import build_registry, gather_status
from lesysbot.management.server import _Handler, _Server


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
    assert code == 200 and json.loads(body)["service"] == "lesysbot-management"


def test_detect_panel_finds_a_running_panel(live):
    """The status screen's liveness probe: our panel answers, a stranger on the
    same port doesn't count, and a dead port reads as offline."""
    from lesysbot.core.status import detect_panel

    settings = live.srv.settings
    got = detect_panel(settings, port=live.port)
    assert got == {"url": f"http://127.0.0.1:{live.port}", "port": live.port, "running": True}

    # something else on the port → not our panel
    other = _Foreign()
    try:
        assert detect_panel(settings, port=other.port)["running"] is False
    finally:
        other.stop()
    # nothing listening at all
    assert detect_panel(settings, port=other.port)["running"] is False


def test_serve_background_binds_once(tmp_path, monkeypatch):
    """The service's panel: a daemon thread on the configured port, and a second
    copy backs off (None) instead of quietly serving somewhere else."""
    import socket

    from lesysbot.management.server import serve_background

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    settings = _make_settings(tmp_path)
    with socket.socket() as s:            # borrow a free port number
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings.management.port = port

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
    from lesysbot.core import grafana, status

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))   # no bundled .env to read
    # explicit env override wins when Grafana really answers there.
    # Patch `core.grafana.api_health` — that is where the probe now lives, and
    # patching anything else lets this reach the developer's real Grafana.
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf:3000")
    monkeypatch.setattr(grafana, "api_health",
                        lambda u, **k: "11.5.1" if "gf" in u else None)
    assert status.detect_grafana() == {
        "url": "http://gf:3000", "version": "11.5.1", "reachable": True}
    # a *stale* override (stack moved off 3000) must not outrank the real Grafana
    monkeypatch.setattr(grafana, "api_health",
                        lambda u, **k: "11.5.1" if "3001" in u else None)
    assert status.detect_grafana()["url"] == "http://localhost:3001"
    # no env: skip whatever's on 3000 (not Grafana), pick the real one on 3001
    monkeypatch.delenv("LESYSBOT_GRAFANA_URL", raising=False)
    assert status.detect_grafana()["url"] == "http://localhost:3001"
    # nothing answers → no link
    monkeypatch.setattr(grafana, "api_health", lambda u, **k: None)
    assert status.detect_grafana() is None
    # …but a configured URL is still reported, flagged unreachable
    monkeypatch.setenv("LESYSBOT_GRAFANA_URL", "http://gf:3000")
    assert status.detect_grafana() == {
        "url": "http://gf:3000", "version": None, "reachable": False}


def test_home_dashboard_url_links_a_provisioned_dashboard(tmp_path):
    """The panel's "Open dashboard" goes to /d/<uid>, not Grafana's home page."""
    import json

    from lesysbot.core import grafana

    assert grafana.home_dashboard_url("http://localhost:3001", tmp_path) is None
    gen = tmp_path / "dashboard" / "grafana" / "dashboards" / "generated"
    gen.mkdir(parents=True)
    (gen / "gpu-detail.json").write_text(json.dumps({"uid": "lesysbot-gpu-detail"}))
    assert (grafana.home_dashboard_url("http://localhost:3001", tmp_path)
            == "http://localhost:3001/d/lesysbot-gpu-detail")
    # System Overview wins over any other dashboard, and a broken file is skipped.
    (gen / "system-overview.json").write_text(json.dumps({"uid": "lesysbot-node"}))
    (gen / "broken.json").write_text("{not json")
    assert (grafana.home_dashboard_url("http://localhost:3001/", tmp_path)
            == "http://localhost:3001/d/lesysbot-node")


def test_grafana_candidates_prefer_the_configured_port(monkeypatch, tmp_path):
    """A stack moved off 3000 (GRAFANA_PORT in dashboard/.env) is probed first."""
    from lesysbot.core import status

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / ".env").write_text("GRAFANA_PORT=3007\n", encoding="utf-8")
    cands = status.grafana_candidates()
    assert cands[:2] == ["http://localhost:3007", "http://127.0.0.1:3007"]
    assert "http://localhost:3000" in cands and len(cands) == len(set(cands))


async def test_gather_status_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    settings = _make_settings(tmp_path)
    st = await gather_status(settings, check_health=False)
    assert st["provider"] == "cli"
    assert st["tools"]["total"] >= 1 and st["tools"]["enabled"] >= 1
    assert st["panel_port"] == settings.management.port
    # probes are skipped with check_health=False…
    assert st["health"] is None and st["grafana"] is None and st["panel"] is None
    # …but the service is reported for every provider, cli included, since it is
    # what serves the control panel (nothing running here → stopped).
    assert st["daemon"] == {"provider": "cli", "pid": None, "running": False}


def _json(live, method, path, body=None):
    """`live.req` returns raw bytes; these endpoints all speak JSON."""
    code, raw = live.req(method, path, body)
    return code, (json.loads(raw) if raw else {})


# ── artifacts, dashboards, doctor and the job table ───────────────────────────
# These back the panel's tabs. The job table is the one genuinely new mechanism:
# an install downloads a zipball and may run pip, which is far too long to hold
# an HTTP request open — a slow network would be indistinguishable from a hung
# panel.

def test_catalog_endpoint_is_gone(live):
    """The marketplace was removed; the panel installs from a link, not an index."""
    assert _json(live, "GET", "/api/catalog")[0] == 404


def test_artifacts_endpoint_is_json_serialisable(live):
    """`source` carries a Path, which would 500 the endpoint if not dropped."""
    code, body = _json(live, "GET", "/api/artifacts")
    assert code == 200 and isinstance(body["artifacts"], list)


def test_dashboard_render_endpoints_are_gone(live):
    """One dashboard, generated by the stack — nothing for the panel to render."""
    assert _json(live, "GET", "/api/dashboards")[0] == 404
    assert _json(live, "POST", "/api/dashboards/render", {})[0] == 404


def test_prereq_endpoint_returns_reports_with_fixes(live):
    code, body = _json(live, "GET", "/api/prereq")
    assert code == 200
    machine = body["reports"][0]
    assert machine["name"] == "this machine"
    for result in machine["results"]:
        assert {"type", "satisfied", "detail", "fix", "auto_fixable"} <= set(result)


def test_unknown_job_is_404(live):
    assert _json(live, "GET", "/api/jobs/nope")[0] == 404


def test_install_returns_a_job_rather_than_blocking(live, monkeypatch):
    import time

    code, body = _json(live, "POST", "/api/artifacts/install", {"source": "acme/does-not-exist"})
    assert code == 202 and body["job"]

    for _ in range(40):
        _, job = _json(live, "GET", f"/api/jobs/{body['job']}")
        if job["state"] != "running":
            break
        time.sleep(0.25)
    # The repo doesn't exist, so it must *fail* — the point is that it failed in
    # the job rather than as a 500 from the request.
    assert job["state"] == "failed" and job["error"]


def test_install_rejects_an_unparseable_source(live):
    code, body = _json(live, "POST", "/api/artifacts/install", {"source": "not-a-link"})
    assert code == 400 and "bad source" in body["error"]


def test_install_requires_a_source(live):
    assert _json(live, "POST", "/api/artifacts/install", {})[0] == 400


def test_install_accepts_a_local_folder(live, tmp_path):
    """The panel takes the same sources the CLI does — a path on disk included."""
    pkg = tmp_path / "greet"
    pkg.mkdir()
    (pkg / "tool.py").write_text(
        "from lesysbot.mcp import tool\n\n\n"
        '@tool(description="hi")\n'
        "async def greet() -> str:\n    return 'hi'\n"
    )
    code, body = _json(live, "POST", "/api/artifacts/install", {"source": str(pkg)})
    assert code == 202 and body["job"]


# -- secrets & the Messaging form ----------------------------------------------
TG_TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
DC_TOKEN = "MTAxMjM0NTY3ODkwMTIzNDU2.GabcDE.fake-discord-token-for-tests_123"

_CFG = f"""\
messaging:
  provider: telegram  # cli | telegram | discord

  telegram:
    token: "{TG_TOKEN}"
    allowed_user_ids: [111]  # Empty = allow everyone

  discord:
    token: "${{DISCORD_TOKEN}}"
    allowed_user_ids: []

llm:
  model: m
  api_key: "sk-proj-0123456789abcdef"  # real key
"""


@pytest.fixture
def cfg_live(tmp_path, monkeypatch):
    """A live panel whose config.yaml holds real-looking secrets."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    monkeypatch.setenv("LESYSBOT_SKIP_SERVICE", "1")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_CFG)
    s = _make_settings(tmp_path)
    s._config_path = cfg
    live = _Live(s)
    yield live, cfg
    live.stop()


def test_config_editor_never_sends_secrets(cfg_live):
    live, cfg = cfg_live
    code, body = live.req("GET", "/api/config")
    assert code == 200
    assert TG_TOKEN.encode() not in body and b"sk-proj-0123456789abcdef" not in body
    text = json.loads(body)["yaml"]
    assert 'token: "<hidden>"' in text
    assert "${DISCORD_TOKEN}" in text          # a reference is not a secret
    assert "# real key" in text                # comments survive masking

    # saving the masked text back keeps the saved secrets, byte for byte
    code, _ = live.req("POST", "/api/config", {"yaml": text.replace("model: m", "model: n")})
    assert code == 200
    assert cfg.read_text() == _CFG.replace("model: m", "model: n")


def test_config_editor_can_replace_a_hidden_secret(cfg_live):
    live, cfg = cfg_live
    text = json.loads(live.req("GET", "/api/config")[1])["yaml"]
    text = text.replace('token: "<hidden>"', 'token: "999:new"', 1)
    assert live.req("POST", "/api/config", {"yaml": text})[0] == 200
    assert 'token: "999:new"' in cfg.read_text()


def test_hidden_without_a_saved_value_is_rejected(cfg_live):
    live, cfg = cfg_live
    cfg.write_text("llm:\n  model: m\n")                 # no token saved anywhere
    code, body = live.req("POST", "/api/config",
                          {"yaml": 'messaging:\n  telegram:\n    token: "<hidden>"\n'})
    assert code == 400 and "type the value" in json.loads(body)["error"]
    assert cfg.read_text() == "llm:\n  model: m\n"


def test_messaging_view_describes_tokens_without_them(cfg_live):
    live, _ = cfg_live
    code, body = live.req("GET", "/api/messaging")
    assert code == 200 and TG_TOKEN.encode() not in body
    d = json.loads(body)
    assert d["provider"] == "telegram" and d["running_provider"] == "cli"
    assert d["telegram"]["token"] == {"state": "set", "hint": TG_TOKEN[-4:]}
    assert d["telegram"]["allowed_user_ids"] == [111]
    assert d["discord"]["token"]["state"] == "env"
    assert d["discord"]["token"]["env_var"] == "DISCORD_TOKEN"
    assert d["restart_needed"] is True
    assert d["service"] == {"installed": False}


def test_messaging_save_keeps_comments_and_untyped_tokens(cfg_live):
    live, cfg = cfg_live
    code, body = live.req("POST", "/api/messaging", {
        "provider": "discord",
        "telegram": {"allowed_user_ids": "111, 222"},          # no token → keep
        "discord": {"token": DC_TOKEN, "allowed_user_ids": [333]},
        "startup_notice": {"enabled": False, "notify": "", "speedtest": True,
                           "speedtest_mb": 2},
    })
    assert code == 200, body
    text = cfg.read_text()
    data = yaml.safe_load(text)
    assert data["messaging"]["provider"] == "discord"
    assert data["messaging"]["telegram"] == {"token": TG_TOKEN, "allowed_user_ids": [111, 222]}
    assert data["messaging"]["discord"] == {"token": DC_TOKEN, "allowed_user_ids": [333]}
    assert data["messaging"]["startup_notice"]["enabled"] is False
    assert data["messaging"]["startup_notice"]["speedtest_mb"] == 2.0
    assert "# cli | telegram | discord" in text and "# real key" in text
    assert data["llm"]["api_key"] == "sk-proj-0123456789abcdef"


def test_messaging_save_validates(cfg_live):
    live, cfg = cfg_live
    before = cfg.read_text()
    for form, msg in [
        ({"provider": "slack"}, "provider must be one of"),
        ({"telegram": {"allowed_user_ids": "me"}}, "not a numeric id"),
        ({"provider": "telegram", "telegram": {"token": ""}}, "needs a bot token"),
        ({"telegram": {"token": "<hidden>"}}, "type the token"),
    ]:
        code, body = live.req("POST", "/api/messaging", form)
        assert code == 400 and msg in json.loads(body)["error"], (form, body)
    assert cfg.read_text() == before


def test_token_test_uses_the_saved_token_when_none_typed(cfg_live, monkeypatch):
    from lesysbot.management import messaging

    seen = {}

    def fake_get(url, headers):
        seen["url"] = url
        return {"ok": True, "result": {"username": "my_bot", "first_name": "Bot"}}

    monkeypatch.setattr(messaging, "_get_json", fake_get)
    live, _ = cfg_live
    code, body = live.req("POST", "/api/messaging/test", {"provider": "telegram", "token": ""})
    assert code == 200 and json.loads(body) == {"ok": True, "bot": "@my_bot", "name": "Bot"}
    assert TG_TOKEN in seen["url"] and TG_TOKEN.encode() not in body


def test_restart_service_queues_without_blocking():
    from lesysbot.management.server import restart_service

    calls = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stderr = rc, b""

    def runner(cmd, **_kw):
        calls.append(cmd)
        return R(0)

    import os
    old = os.environ.pop("LESYSBOT_SKIP_SERVICE", None)
    try:
        import shutil
        if not shutil.which("systemctl"):
            pytest.skip("no systemctl")
        assert restart_service(runner)["ok"] is True
    finally:
        if old is not None:
            os.environ["LESYSBOT_SKIP_SERVICE"] = old
    assert calls[-1] == ["systemctl", "--user", "--no-block", "restart", "lesysbot"]
