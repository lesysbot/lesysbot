"""Tests for the control-panel server and the shared status snapshot."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

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


# ── credentials in the Config tab ─────────────────────────────────────────────
# The panel hands a whole config.yaml to a browser, so the tokens in it must not
# travel with it — but editing anything else must not cost the user a retyped
# token either. Fabricated placeholders below; NOT real credentials.

TG_TOKEN = "0000000000:AA-FAKE-placeholder-not-a-real-token-00"
DISCORD_TOKEN = "FAKEfakeFAKEfakeFAKEfak.FAKE12.notarealdiscordtokenvalue00"
API_KEY = "sk-fake-placeholder-key-000000000000"

CONFIG_WITH_SECRETS = f"""\
messaging:
  provider: cli
  telegram:
    token: "{TG_TOKEN}"
  discord:
    token: {DISCORD_TOKEN}
llm:
  model: m
  api_key: {API_KEY}
"""


@pytest.fixture
def secret_config(live, tmp_path):
    """A real config file on disk (the panel reads it per request)."""
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_WITH_SECRETS)
    return path


def test_config_masks_credentials(live, secret_config):
    _, body = _json(live, "GET", "/api/config")
    shown = body["yaml"]
    assert body["masked"] is True
    for secret in (TG_TOKEN, DISCORD_TOKEN, API_KEY):
        assert secret not in shown
        assert "****" + secret[-4:] in shown        # last four still identify it
    assert "model: m" in shown                      # nothing else is touched


def test_saving_masked_values_keeps_the_stored_credentials(live, secret_config):
    _, body = _json(live, "GET", "/api/config")
    edited = body["yaml"].replace("model: m", "model: changed")
    code, body = _json(live, "POST", "/api/config", {"yaml": edited})
    assert code == 200 and body["ok"] is True
    on_disk = secret_config.read_text()
    assert "model: changed" in on_disk
    for secret in (TG_TOKEN, DISCORD_TOKEN, API_KEY):
        assert secret in on_disk                    # survived the round trip
    assert "****" not in on_disk


def test_typing_a_new_token_replaces_it(live, secret_config):
    _, body = _json(live, "GET", "/api/config")
    new = "1111111111:BB-FAKE-placeholder-not-a-real-token-11"
    edited = body["yaml"].replace('"****' + TG_TOKEN[-4:] + '"', f'"{new}"')
    assert _json(live, "POST", "/api/config", {"yaml": edited})[0] == 200
    on_disk = secret_config.read_text()
    assert new in on_disk and TG_TOKEN not in on_disk


def test_placeholders_and_env_references_stay_readable(live, tmp_path):
    """Masking `ollama` or `${VAR}` would hide nothing and read as data loss."""
    (tmp_path / "config.yaml").write_text(
        'llm:\n  api_key: ollama\nmessaging:\n  telegram:\n    token: ${TG_TOKEN}\n')
    _, body = _json(live, "GET", "/api/config")
    assert body["masked"] is False
    assert "api_key: ollama" in body["yaml"] and "${TG_TOKEN}" in body["yaml"]


def test_ambiguous_mask_is_refused_rather_than_guessed(live, tmp_path):
    """Two credentials with the same last four: restoring blind could swap them."""
    (tmp_path / "config.yaml").write_text(
        "messaging:\n"
        "  telegram:\n    token: 0000000000:AA-fake-placeholder-token-TAIL\n"
        "  discord:\n    token: FAKEfakeFAKEfakeFAKEfak.FAKE12.otherfaketokenTAIL\n")
    _, body = _json(live, "GET", "/api/config")
    assert body["yaml"].count("****TAIL") == 2
    code, body = _json(live, "POST", "/api/config", {"yaml": body["yaml"]})
    assert code == 400 and "in full" in body["error"]


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


# ── marketplace, dashboards, doctor and the job table ─────────────────────────
# These back the panel's new tabs. The job table is the one genuinely new
# mechanism: an install downloads a zipball and may run pip, which is far too
# long to hold an HTTP request open — a slow network would be indistinguishable
# from a hung panel.

def test_catalog_endpoint_marks_what_runs_here_and_what_is_installed(live):
    code, body = _json(live, "GET", "/api/catalog")
    assert code == 200
    for entry in body["entries"]:
        assert {"id", "kind", "source", "runs_here", "installed"} <= set(entry)
        # The guarantee that makes the catalog safe: it only ever hands back a
        # GitHub link, which the installer parses like any other.
        from lesysbot.artifacts.spec import parse_source

        parse_source(entry["source"])


def test_artifacts_endpoint_is_json_serialisable(live):
    """`source` carries a Path, which would 500 the endpoint if not dropped."""
    code, body = _json(live, "GET", "/api/artifacts")
    assert code == 200 and isinstance(body["artifacts"], list)


def test_dashboards_endpoint_reports_state(live):
    code, body = _json(live, "GET", "/api/dashboards")
    assert code == 200 and isinstance(body["dashboards"], list)


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


def test_install_rejects_an_unresolvable_source(live):
    code, body = _json(live, "POST", "/api/artifacts/install", {"source": "not-a-link"})
    assert code == 400 and "not a GitHub link" in body["error"]


def test_install_requires_a_source(live):
    assert _json(live, "POST", "/api/artifacts/install", {})[0] == 400


# -- the advertised Grafana link -----------------------------------------------

def test_status_links_the_dashboard_once_it_is_provisioned(tmp_path, monkeypatch):
    """One dashboard at one uid means there is a single URL worth handing over.

    Grafana's landing page is an extra click and a folder to find, so the status
    screen and the panel point at `/d/lesysbot` instead — but only once the file
    exists, because advertising a 404 is worse than the generic link.
    """
    from lesysbot.core import status
    from lesysbot.core.paths import generated_dashboards_dir
    from lesysbot.dashboards.render import OUTPUT_NAME

    class _S:
        config_dir = tmp_path

    grafana = {"url": "http://localhost:3000", "reachable": True, "version": "11.5.1"}

    # Nothing rendered yet — no direct link offered.
    status._add_dashboard_url(grafana, _S())
    assert "dashboard_url" not in grafana

    generated = generated_dashboards_dir(tmp_path)
    generated.mkdir(parents=True, exist_ok=True)
    (generated / OUTPUT_NAME).write_text("{}")

    status._add_dashboard_url(grafana, _S())
    assert grafana["dashboard_url"] == "http://localhost:3000/d/lesysbot"


def test_an_unreachable_grafana_gets_no_dashboard_link(tmp_path):
    """A saved URL that nothing answers must not be dressed up as a working link."""
    from lesysbot.core import status

    class _S:
        config_dir = tmp_path

    grafana = {"url": "http://localhost:3000", "reachable": False}
    status._add_dashboard_url(grafana, _S())
    assert "dashboard_url" not in grafana

    status._add_dashboard_url(None, _S())      # nothing configured at all
