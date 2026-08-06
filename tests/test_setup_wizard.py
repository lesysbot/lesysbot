"""Setup wizard: step chain navigation, config writing, seeding, services.

Drives the wizard through a scripted FakeUI — no terminal, no subprocesses
(service functions get a recording runner), hermetic via LESYSBOT_HOME/HOME
monkeypatching like the rest of the suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from lesysbot.core.config import LLMConfig
from lesysbot.setup import apply as apply_mod
from lesysbot.setup import wizard
from lesysbot.setup.wizard import SetupAborted, WizardState

DEFAULT = object()  # scripted answer meaning "accept the offered default"


@pytest.fixture(autouse=True)
def _empty_bundle(tmp_path_factory, monkeypatch):
    """Point `bundled_dir()` at an empty directory for the whole module.

    Seeding no longer needs `--repo`: with no checkout it falls back to the
    content that shipped in the wheel, which in a dev checkout is the repo
    itself. Left alone, every wizard test here would seed the developer's real
    tools/ and dashboard/ into a temp home — slow, and it makes the assertions
    depend on whatever happens to be in the tree.
    """
    empty = tmp_path_factory.mktemp("empty-bundle")
    monkeypatch.setattr("lesysbot.core.paths.bundled_dir", lambda: empty)


class FakeUI:
    interactive = True

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []  # (kind, label, offered_default)
        self.messages = []  # everything printed via say/note/ok/warn
        self.eof = False

    def _pop(self, kind, label, default):
        self.calls.append((kind, label, default))
        assert self.answers, f"wizard asked more than scripted: {kind} {label!r}"
        expect_kind, value = self.answers.pop(0)
        assert expect_kind == kind, (
            f"script expected {expect_kind!r} next, wizard asked {kind} {label!r}"
        )
        return default if value is DEFAULT else value

    def menu(self, title, options, default=1):
        return self._pop("menu", title, default)

    def text(self, prompt, default="", secret=False):
        return self._pop("text", prompt, default)

    def confirm_yn(self, prompt, default=True):
        return self._pop("confirm", prompt, default)

    def say(self, text="", *_args, **_kw):
        self.messages.append(str(text))

    note = ok = warn = say


def custom_llm_answers(url="http://x:1/v1", model="m1", key="k1"):
    return [("menu", 4), ("text", url), ("text", model), ("text", key)]


def test_back_from_messaging_preserves_llm_answers():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 4),           # messaging: ← Back
            ("menu", DEFAULT),     # LLM menu re-shown, default = Custom (4)
            ("text", DEFAULT),     # previous answers offered as defaults
            ("text", DEFAULT),
            ("text", DEFAULT),
            ("menu", 1),           # Terminal only
            ("menu", 1),           # service: start now + at reboot
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_choice == 4
    assert (st.llm_base_url, st.llm_model, st.llm_api_key) == ("http://x:1/v1", "m1", "k1")
    assert st.msg_provider == "cli"
    # The service is installed for every provider — it serves the control panel.
    assert st.needs_service is True
    # The revisited LLM menu offered the previous choice as its default…
    revisit_menu = [c for c in ui.calls if c[0] == "menu" and c[1].startswith("Step 1")][1]
    assert revisit_menu[2] == 4
    # …and the revisited prompts offered the previous answers.
    revisit_url = [c for c in ui.calls if c[0] == "text"][3]
    assert revisit_url[2] == "http://x:1/v1"


def test_backend_switch_clears_followup_answers():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 4),           # messaging: ← Back
            ("menu", 3),           # switch backend to vLLM
            ("text", DEFAULT),     # base URL — must offer the vLLM default
            ("text", DEFAULT),     # model — must offer the vLLM default
            ("menu", 1),           # Terminal only
            ("menu", 1),           # service
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_base_url == "http://localhost:8000/v1"
    assert st.llm_model == "meta-llama/Llama-3.2-8B-Instruct"
    assert st.llm_api_key == "vllm"
    vllm_url_prompt = [c for c in ui.calls if c[0] == "text"][3]
    assert vllm_url_prompt[2] == "http://localhost:8000/v1"  # not the stale custom URL


def test_esc_at_prompt_reshows_step_menu():
    ui = FakeUI(
        [
            ("menu", 4),
            ("text", None),        # Esc at Base URL → back to this step's menu
            ("menu", 4),
            ("text", "http://y/v1"),
            ("text", "m"),
            ("text", "k"),
            ("menu", 1),           # Terminal only
            ("menu", 1),           # service
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_base_url == "http://y/v1"
    assert len([c for c in ui.calls if c[0] == "menu" and c[1].startswith("Step 1")]) == 2


def test_telegram_ids_validated_and_esc_backs_out():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 2),           # Telegram
            ("text", "tok"),
            ("text", "abc"),       # invalid IDs → re-asked
            ("text", None),        # Esc at IDs → back to messaging menu
            ("menu", 2),           # Telegram again (token remembered)
            ("text", DEFAULT),
            ("text", "42, 43"),    # spaces stripped, then valid
            ("menu", 2),           # service: start now only
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.msg_provider == "telegram"
    assert st.tg_token == "tok"
    assert st.tg_allowed_ids == "[42, 43]"
    assert st.auto_start is False
    assert st.needs_service is True


def test_telegram_ids_eof_aborts():
    ui = FakeUI([*custom_llm_answers(), ("menu", 2), ("text", "tok"), ("text", "")])
    ui.eof = True  # piped input has run dry; "" is invalid and can never improve
    st = WizardState()
    with pytest.raises(SetupAborted):
        wizard.run_steps(ui, st, 1)


def test_summary_change_reach_and_apply(tmp_path):
    st = WizardState(llm_choice=4, llm_base_url="u", llm_model="m", llm_api_key="k")
    ui = FakeUI(
        [
            ("menu", 3),           # summary: Change how to reach LeSysBot
            ("menu", 3),           # messaging: Discord
            ("text", "dtok"),      # bot token
            ("text", "42"),        # allowed user ids
            ("menu", 1),           # service: start now + reboot
            ("menu", 1),           # summary: Apply
        ]
    )
    assert wizard.step_summary(ui, st, tmp_path) is True
    assert st.msg_provider == "discord"
    assert st.dc_token == "dtok"
    assert st.dc_allowed_ids == "[42]"
    assert st.auto_start is True
    # With a service pending, the summary menu grows the startup entry.
    summary_menus = [c for c in ui.calls if c[0] == "menu" and c[1] == "Ready?"]
    assert len(summary_menus) == 2


def test_summary_quit_without_writing(tmp_path):
    st = WizardState()
    ui = FakeUI([("menu", 5)])  # Apply / LLM / reach / startup / Quit
    assert wizard.step_summary(ui, st, tmp_path) is False


def test_write_config_roundtrip(tmp_path):
    st = WizardState(
        llm_base_url="http://x/v1",
        llm_model="mm",
        llm_api_key="kk",
        msg_provider="telegram",
        tg_token="t0k",
        tg_allowed_ids="[1, 2]",
    )
    path = apply_mod.write_config(st, tmp_path)
    cfg = yaml.safe_load(path.read_text())
    assert cfg["messaging"]["provider"] == "telegram"
    assert cfg["messaging"]["telegram"]["token"] == "t0k"
    assert cfg["messaging"]["telegram"]["allowed_user_ids"] == [1, 2]
    assert cfg["llm"]["base_url"] == "http://x/v1"
    assert cfg["llm"]["model"] == "mm"
    assert cfg["mcp"]["tools_dir"] == "./tools"


def test_write_config_discord_roundtrip(tmp_path):
    st = WizardState(
        llm_base_url="http://x/v1",
        llm_model="mm",
        llm_api_key="kk",
        msg_provider="discord",
        dc_token="d0k",
        dc_allowed_ids="[7, 8]",
    )
    cfg = yaml.safe_load(apply_mod.write_config(st, tmp_path).read_text())
    assert cfg["messaging"]["provider"] == "discord"
    assert cfg["messaging"]["discord"]["token"] == "d0k"
    assert cfg["messaging"]["discord"]["allowed_user_ids"] == [7, 8]


def test_read_provider(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("messaging:\n  provider: discord\n")
    assert apply_mod.read_provider(cfg) == "discord"
    cfg.write_text("# nothing\n")
    assert apply_mod.read_provider(cfg) == "cli"


def test_read_config_state_round_trips_a_written_config(tmp_path):
    written = WizardState(
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
        llm_api_key="sk-xyz",
        msg_provider="telegram",
        tg_token="t0k",
        tg_allowed_ids="[1, 2]",
    )
    path = apply_mod.write_config(written, tmp_path)

    st = apply_mod.read_config_state(path)
    assert (st.llm_model, st.llm_base_url) == ("gpt-4o", "https://api.openai.com/v1")
    assert st.llm_api_key == "sk-xyz"
    assert st.llm_choice == 2                      # OpenAI, from the base URL
    assert (st.msg_provider, st.msg_choice) == ("telegram", 2)
    assert st.tg_token == "t0k"
    assert (st.tg_raw_ids, st.tg_allowed_ids) == ("1,2", "[1, 2]")


def test_read_config_state_falls_back_and_survives_junk(tmp_path):
    cfg = tmp_path / "config.yaml"
    # Keys a config may legitimately omit fall back to what the bot actually
    # runs on (the model defaults), never to blanks.
    cfg.write_text("messaging:\n  provider: cli\n")
    st = apply_mod.read_config_state(cfg)
    fallback = LLMConfig()                         # whatever the bot ships as default
    assert (st.llm_model, st.llm_base_url) == (fallback.model, fallback.base_url)
    assert st.llm_model and st.llm_base_url        # …and never blank
    assert st.llm_choice == 1                      # Ollama
    assert st.msg_provider == "cli"

    cfg.write_text("llm:\n  base_url: http://localhost:8000/v1\n  api_key: vllm\n")
    assert apply_mod.read_config_state(cfg).llm_choice == 3

    cfg.write_text(":\n  not: [valid\n")            # unparseable → plain defaults
    assert apply_mod.read_config_state(cfg) == WizardState()
    assert apply_mod.read_config_state(tmp_path / "missing.yaml") == WizardState()


def test_seed_tools_copies_once_and_skips_pycache(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tools" / "demo").mkdir(parents=True)
    (repo / "tools" / "demo" / "tool.py").write_text("x = 1\n")
    (repo / "tools" / "__pycache__").mkdir()
    data = tmp_path / "home"
    data.mkdir()
    assert apply_mod.seed_tools(repo, data) is True
    assert (data / "tools" / "demo" / "tool.py").exists()
    assert not (data / "tools" / "__pycache__").exists()

    # Re-seeding is a no-op when nothing changed — but it is a *refresh*, not a
    # bail-out. The old behaviour returned False because the directory existed,
    # which is why a fix to a bundled tool could never reach an existing install.
    assert apply_mod.seed_tools(repo, data) is False

    (repo / "tools" / "demo" / "tool.py").write_text("x = 2   # fixed\n")
    assert apply_mod.seed_tools(repo, data) is True
    assert "fixed" in (data / "tools" / "demo" / "tool.py").read_text()

    # And it is recorded, so `lesysbot list` can say where it came from.
    from lesysbot.artifacts.kinds import ArtifactKind
    from lesysbot.artifacts.lockfile import ArtifactLock

    entry = ArtifactLock(data / "lesysbot.lock.json").get(ArtifactKind.TOOL, "demo")
    assert entry["bundled"] is True

    # No checkout and no bundle (the autouse fixture empties it) — nothing to do.
    assert apply_mod.seed_tools(None, data) is False


def test_seed_tools_preserves_what_the_manifest_names(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "tools" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "tool.py").write_text("x = 1\n")
    (pkg / "README.md").write_text("---\nname: demo\npreserve: [\".env\"]\n---\n")
    data = tmp_path / "home"
    data.mkdir()

    apply_mod.seed_tools(repo, data)
    (data / "tools" / "demo" / ".env").write_text("TOKEN=mine\n")

    (pkg / "tool.py").write_text("x = 2\n")
    apply_mod.seed_tools(repo, data)
    assert (data / "tools" / "demo" / ".env").read_text() == "TOKEN=mine\n"


def _fake_stack(data_dir: Path) -> Path:
    """A minimal seeded dashboard/ dir with the stack scripts, for start tests."""
    mon = data_dir / "dashboard"
    (mon / "scripts").mkdir(parents=True)
    (mon / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (mon / "scripts" / "start.ps1").write_text("")
    (mon / "scripts" / "install-macos.sh").write_text("#!/usr/bin/env bash\n")
    return mon


def test_seed_dashboard_copies_once_and_skips_runtime(tmp_path):
    repo = tmp_path / "repo"
    (repo / "dashboard" / "scripts").mkdir(parents=True)
    (repo / "dashboard" / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "dashboard" / ".env.example").write_text("GRAFANA_PORT=3000\n")
    (repo / "dashboard" / "bin").mkdir()          # downloaded exporter binaries
    (repo / "dashboard" / "bin" / "node_exporter").write_text("ELF")
    (repo / "dashboard" / "__pycache__").mkdir()
    data = tmp_path / "home"
    data.mkdir()
    assert apply_mod.seed_dashboard(repo, data) is True
    assert (data / "dashboard" / "scripts" / "start.sh").exists()
    assert not (data / "dashboard" / "bin").exists()        # runtime dir skipped
    assert not (data / "dashboard" / "__pycache__").exists()
    assert (data / "dashboard" / ".env").read_text() == "GRAFANA_PORT=3000\n"  # seeded
    assert (data / "dashboard" / "scripts" / "start.sh").stat().st_mode & 0o111 == 0
    # Nothing new to add on a re-run; None repo is a no-op.
    assert apply_mod.seed_dashboard(repo, data) is False
    assert apply_mod.seed_dashboard(None, data) is False


def test_seed_dashboard_adds_new_files_and_refreshes_shipped_ones(tmp_path):
    """An upgrade has to deliver both new files and fixes to existing ones.

    Seeding once bailed out whenever the stack dir existed, so a stack that gained
    a script could never deliver it; then it added missing files but never
    updated changed ones, which made the shipped scripts and dashboards
    unpatchable — an install kept running last release's code forever. Both are
    the same bug seen from different angles, so both are pinned here.
    """
    repo = tmp_path / "repo"
    (repo / "dashboard" / "scripts").mkdir(parents=True)
    (repo / "dashboard" / "scripts" / "start.sh").write_text("new upstream\n")
    (repo / "dashboard" / ".env.example").write_text("GRAFANA_PORT=3000\n")
    data = tmp_path / "home"
    (data / "dashboard" / "scripts").mkdir(parents=True)
    (data / "dashboard" / "scripts" / "start.sh").write_text("last release\n")
    (data / "dashboard" / ".env").write_text("GRAFANA_PORT=3005\n")

    # The upgrade adds a new script…
    installer = repo / "dashboard" / "scripts" / "install-macos.sh"
    installer.write_text("#!/usr/bin/env bash\n")
    installer.chmod(0o755)
    assert apply_mod.seed_dashboard(repo, data) is True
    seeded = data / "dashboard" / "scripts" / "install-macos.sh"
    assert seeded.exists()
    assert seeded.stat().st_mode & 0o111          # …executable, or bash can't run it
    # …and refreshes the stale one it already had.
    assert (data / "dashboard" / "scripts" / "start.sh").read_text() == "new upstream\n"
    assert apply_mod.seed_dashboard(repo, data) is False   # idempotent once current


def test_seed_dashboard_never_touches_user_owned_files(tmp_path):
    """`.env` (ports, Grafana login) and prometheus/ (hand-added scrape targets)
    are the two places a user customises. A refresh that clobbered either would
    silently undo their setup — moving Grafana back onto a taken port, or
    dropping a host they added."""
    repo = tmp_path / "repo"
    (repo / "dashboard" / "prometheus").mkdir(parents=True)
    (repo / "dashboard" / "prometheus" / "prometheus.yml").write_text("upstream targets\n")
    (repo / "dashboard" / ".env.example").write_text("GRAFANA_PORT=3000\n")
    (repo / "dashboard" / ".env").write_text("GRAFANA_PORT=3000\n")
    data = tmp_path / "home"
    (data / "dashboard" / "prometheus").mkdir(parents=True)
    (data / "dashboard" / "prometheus" / "prometheus.yml").write_text("my extra host\n")
    (data / "dashboard" / ".env").write_text("GRAFANA_PORT=3005\n")

    apply_mod.seed_dashboard(repo, data)
    assert (data / "dashboard" / "prometheus" / "prometheus.yml").read_text() == "my extra host\n"
    assert (data / "dashboard" / ".env").read_text() == "GRAFANA_PORT=3005\n"


def test_seed_dashboard_delivers_a_dashboard_fix(tmp_path):
    """The concrete case this exists for: a regenerated dashboard has to reach an
    install that already has the old one, or the fix never lands."""
    repo = tmp_path / "repo"
    dash = repo / "dashboard" / "grafana" / "dashboards"
    dash.mkdir(parents=True)
    (dash / "system-overview-linux-macos.json").write_text('{"version": 2}')
    (repo / "dashboard" / ".env.example").write_text("GRAFANA_PORT=3000\n")
    data = tmp_path / "home"
    old = data / "dashboard" / "grafana" / "dashboards"
    old.mkdir(parents=True)
    (old / "system-overview-linux-macos.json").write_text('{"version": 1}')

    assert apply_mod.seed_dashboard(repo, data) is True
    assert (old / "system-overview-linux-macos.json").read_text() == '{"version": 2}'


def test_start_dashboard_env_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_SKIP_DASHBOARD", "1")
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    _fake_stack(tmp_path)
    runner = Recorder(returncode=0)
    assert apply_mod.start_dashboard(FakeUI([]), tmp_path, runner=runner) is False
    assert runner.calls == []  # skipped before any docker call


def test_start_dashboard_no_dir_is_noop(tmp_path):
    runner = Recorder(returncode=0)
    assert apply_mod.start_dashboard(FakeUI([]), tmp_path, runner=runner) is False
    assert runner.calls == []


class DockerRunner:
    """Docker present; `docker info` (the daemon probe) rc follows ``daemon_up``.
    Everything else (compose version, bash start.sh) returns 0."""

    def __init__(self, daemon_up=True):
        self.calls = []
        self.daemon_up = daemon_up

    def __call__(self, cmd, **_kw):
        import subprocess

        self.calls.append(cmd)
        rc = 0 if (cmd[:2] != ["docker", "info"] or self.daemon_up) else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")


def _said(ui, needle: str) -> bool:
    return any(needle in m for m in ui.messages)


def _ran_script(runner, name: str) -> bool:
    """Did the runner invoke ``bash …/<name> …``? Matched on the script argument
    only — a tmp_path can easily contain the word 'start'."""
    return any(
        c and c[0] == "bash" and any(str(a).endswith(name) for a in c[1:])
        for c in runner.calls
    )


def _ran_stack(runner) -> bool:
    return _ran_script(runner, "start.sh") or _ran_script(runner, "start.ps1")


def _ran_brew_install(runner) -> bool:
    return _ran_script(runner, "install-macos.sh")


def _which(**found):
    """A ``shutil.which`` stub: ``_which(brew=True)`` finds brew and nothing else."""
    return lambda name: f"/usr/local/bin/{name}" if found.get(name) else None


# Every start_dashboard path first asks the Grafana username + password; accept
# the admin/admin defaults unless a test wants specific values.
CREDS = [("text", DEFAULT), ("text", DEFAULT)]


# ── Grafana credential prompt + persistence ───────────────────────────────────
def test_interactive_text_masks_secret(monkeypatch):
    import io
    from contextlib import nullcontext

    from rich.console import Console

    from lesysbot.setup import ui as ui_mod

    keys = iter(["s", "e", "c", "r", "e", "t", "enter"])
    monkeypatch.setattr(ui_mod, "raw_mode", nullcontext)
    monkeypatch.setattr(ui_mod, "read_key", lambda: next(keys))
    console = Console(file=io.StringIO(), record=True, force_terminal=False, width=100)
    value = ui_mod.InteractiveUI(console=console).text(
        "Grafana password", default="admin", secret=True)
    assert value == "secret"
    out = console.export_text()
    assert "secret" not in out   # the typed password never appears in cleartext
    assert "admin" not in out    # nor does the (masked) default
    assert "*" in out            # a masked echo is shown instead


def test_write_grafana_env_roundtrip(tmp_path):
    path = apply_mod.write_grafana_env(tmp_path, "http://gf:3000", "bob", "s3cret-pass-1")
    from lesysbot.core.paths import parse_env_file

    pairs = parse_env_file(path)
    assert pairs["LESYSBOT_GRAFANA_URL"] == "http://gf:3000"
    assert pairs["LESYSBOT_GRAFANA_USER"] == "bob"
    assert pairs["LESYSBOT_GRAFANA_PASSWORD"] == "s3cret-pass-1"


def test_ask_grafana_credentials_defaults_then_prev(tmp_path):
    # No file yet → admin/admin defaults offered and accepted.
    ui = FakeUI(CREDS)
    assert apply_mod.ask_grafana_credentials(ui, tmp_path) == (
        "http://localhost:3000", "admin", "admin")
    # Save custom values, then a later run offers them as the defaults.
    apply_mod.write_grafana_env(tmp_path, "http://gf:3000", "bob", "pw-123456789")
    ui = FakeUI(CREDS)
    assert apply_mod.ask_grafana_credentials(ui, tmp_path) == (
        "http://gf:3000", "bob", "pw-123456789")


def test_grafana_url_follows_the_stacks_port(tmp_path):
    """A stack moved off 3000 must be advertised on its real port, and a saved
    localhost URL from an earlier run must not pin it back to 3000."""
    mon = _fake_stack(tmp_path)
    (mon / ".env").write_text("GRAFANA_PORT=3001\n", encoding="utf-8")
    assert apply_mod.grafana_port(mon) == "3001"
    assert apply_mod.default_grafana_url(tmp_path) == "http://localhost:3001"

    apply_mod.write_grafana_env(tmp_path, "http://localhost:3000", "bob", "pw-123456789")
    assert apply_mod.default_grafana_url(tmp_path) == "http://localhost:3001"
    assert apply_mod.ask_grafana_credentials(FakeUI(CREDS), tmp_path)[0] == "http://localhost:3001"

    # a remote Grafana is a deliberate choice — keep it
    apply_mod.write_grafana_env(tmp_path, "http://gf.example:3000", "bob", "pw-123456789")
    assert apply_mod.default_grafana_url(tmp_path) == "http://gf.example:3000"

    # no/garbled GRAFANA_PORT → the documented default
    (mon / ".env").write_text("GRAFANA_PORT=\n", encoding="utf-8")
    assert apply_mod.grafana_port(mon) == "3000"


def test_epilogue_advertises_the_real_grafana_port_and_login(tmp_path):
    """The closing summary is where most people get the dashboard link, and it
    used to hardcode `localhost:3000` + `admin / admin` — so a stack on 3001, or
    a login the wizard had *just* asked for, was advertised wrongly."""
    mon = _fake_stack(tmp_path)
    (mon / ".env").write_text("GRAFANA_PORT=3001\n", encoding="utf-8")
    apply_mod.write_grafana_env(tmp_path, "http://localhost:3001", "bob", "pw-123456789")

    ui = FakeUI([])
    apply_mod.print_epilogue(ui, "cli", needs_service=True, data_dir=tmp_path)
    out = "\n".join(ui.messages)

    assert "http://localhost:3001" in out
    assert "http://localhost:3000" not in out
    assert "log in as bob" in out
    # The password is masked at the prompt; echoing it here would undo that.
    assert "pw-123456789" not in out


def test_start_dashboard_saves_grafana_env_and_docker_env(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    mon = _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=True)
    # Way (menu) first, then the Grafana username + password.
    ui = FakeUI([("menu", 1), ("text", "bob"), ("text", "pw-123456789")])
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is True
    from lesysbot.core.paths import parse_env_file

    saved = parse_env_file(tmp_path / "grafana.env")
    assert (saved["LESYSBOT_GRAFANA_USER"], saved["LESYSBOT_GRAFANA_PASSWORD"]) == (
        "bob", "pw-123456789")
    # The bundled Docker Grafana is pointed at the same admin login.
    docker_env = (mon / ".env").read_text()
    assert "GRAFANA_ADMIN_USER=bob" in docker_env
    assert "GRAFANA_ADMIN_PASSWORD=pw-123456789" in docker_env


# ── Linux: ask auto-start vs. manual (when Docker is running) ──────────────────
def test_start_dashboard_linux_auto_start(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=True)
    ui = FakeUI([("menu", 1), *CREDS])  # way first, then login
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is True
    assert _ran_stack(runner)


def test_start_dashboard_linux_manual_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=True)
    ui = FakeUI([("menu", 2), *CREDS])  # way first (manual), then login
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)  # nothing started; just told how


def test_start_dashboard_linux_docker_not_installed(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_stack(tmp_path)
    runner = DockerRunner()
    ui = FakeUI([*CREDS])  # no menu asked when Docker isn't ready
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)
    assert _said(ui, "docker.com/engine/install")
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)  # native-Grafana alternative offered


def test_start_dashboard_linux_daemon_down(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)
    assert _said(ui, "daemon isn't reachable")


# ── macOS: install natively with Homebrew (no Docker Desktop) ─────────────────
def test_start_dashboard_macos_brew_auto_install(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", _which(brew=True))
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=False)  # Docker is irrelevant on this path
    ui = FakeUI([("menu", 1), *CREDS])      # way first, then the login
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is True
    assert _ran_brew_install(runner)
    assert not _ran_stack(runner)           # the Docker stack is never touched


def test_start_dashboard_macos_brew_manual_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", _which(brew=True))
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([("menu", 2), *CREDS])      # way first (manual), then the login
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_brew_install(runner)    # nothing installed; just told how
    assert _said(ui, "install-macos.sh")


def test_start_dashboard_macos_brew_manual_mentions_docker_when_running(
        tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", _which(brew=True, docker=True))
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=True)   # Docker running → offer it as an option
    ui = FakeUI([("menu", 2), *CREDS])
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert _said(ui, "start.sh")            # the bundled-stack alternative


def test_start_dashboard_macos_without_the_script_says_so(tmp_path, monkeypatch):
    """A dashboard/ folder older than install-macos.sh must not look like a
    failure of the automatic path — name the missing file and how to seed it."""
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", _which(brew=True))
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    mon = _fake_stack(tmp_path)
    (mon / "scripts" / "install-macos.sh").unlink()
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_brew_install(runner)
    assert _said(ui, "install-macos.sh")
    assert _said(ui, "--repo")                    # how to seed it
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)  # and the manual route meanwhile


def test_start_dashboard_macos_without_brew_instructs(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", _which())  # no brew, no docker
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])                   # no menu — there's nothing to automate
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert not _ran_brew_install(runner)
    assert _said(ui, apply_mod.BREW_INSTALL)      # how to get the automatic path
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)  # how to install Grafana by hand
    assert _said(ui, "LESYSBOT_GRAFANA_URL")      # how to connect it


# ── Windows: warn + instruct native Grafana ───────────────────────────────────


def test_start_dashboard_windows_instructs(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(apply_mod.sys, "platform", "win32")
    _fake_stack(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])
    assert apply_mod.start_dashboard(ui, tmp_path, runner=runner) is False
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)


class Recorder:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd)
        import subprocess

        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr="")


@pytest.mark.skipif(
    os.name == "nt",
    reason="systemd --user is Linux-only; on Windows Path.home() keys off USERPROFILE "
           "(not the patched HOME) and the POSIX /data path renders as \\data",
)
def test_setup_service_linux_writes_unit_and_enables(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    st = WizardState(auto_start=True)
    runner = Recorder()
    ui = FakeUI([])
    apply_mod.setup_service_linux(ui, st, Path("/data"), runner=runner)
    unit = tmp_path / ".config" / "systemd" / "user" / "lesysbot.service"
    assert unit.exists()
    assert "WorkingDirectory=/data" in unit.read_text()
    flat = [" ".join(c) for c in runner.calls]
    assert any("enable lesysbot" in c for c in flat)
    assert any("restart lesysbot" in c for c in flat)


def _no_real_service(monkeypatch) -> list:
    """Record service setup instead of touching systemd/launchd/Task Scheduler."""
    installed: list = []
    monkeypatch.setattr(apply_mod, "setup_service",
                        lambda ui, st, data_dir, **_kw: installed.append((st.msg_provider,
                                                                         st.auto_start)))
    return installed


def test_cli_run_fresh_config(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = _no_real_service(monkeypatch)
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 1),           # Terminal only
            ("menu", 2),           # service: start now only
            ("menu", 1),           # summary: Apply
        ]
    )
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda **_kw: ui)
    args = argparse.Namespace(command="setup", repo=None)
    assert setup_cli.run(args) == 0
    cfg = yaml.safe_load((tmp_path / "home" / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "cli"
    assert cfg["llm"]["model"] == "m1"
    # Even a terminal-only install gets the service — it serves the control panel.
    assert installed == [("cli", False)]


def test_cli_run_seeds_and_attempts_dashboard(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    # A repo checkout with a dashboard/ stack to seed from.
    repo = tmp_path / "repo"
    (repo / "dashboard" / "scripts").mkdir(parents=True)
    (repo / "dashboard" / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "dashboard" / ".env.example").write_text("GRAFANA_PORT=3000\n")

    home = tmp_path / "home"
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    _no_real_service(monkeypatch)
    # Docker not ready → start_dashboard only prints instructions (no subprocess).
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    # LLM (custom) → messaging (terminal) → service → summary Apply → Grafana login.
    ui = FakeUI([*custom_llm_answers(), ("menu", 1), ("menu", 1), ("menu", 1),
                 ("text", DEFAULT), ("text", DEFAULT)])
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda **_kw: ui)
    args = argparse.Namespace(command="setup", repo=str(repo))
    assert setup_cli.run(args) == 0
    # The dashboard stack was seeded into the installed home as a standard part.
    assert (home / "dashboard" / "scripts" / "start.sh").exists()
    assert (home / "dashboard" / ".env").exists()
    # And the Grafana login LeSysBot will use was saved for startup.
    assert (home / "grafana.env").exists()


def test_cli_run_keeps_existing_config(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    home = tmp_path / "home"
    home.mkdir()
    existing = (
        "messaging:\n"
        "  provider: telegram\n"
        "  telegram:\n"
        '    token: "t0k"\n'
        "    allowed_user_ids: [42, 43]\n"
        "llm:\n"
        '  base_url: "http://localhost:11434/v1"\n'
        '  model: "qwen3:8b"\n'
    )
    (home / "config.yaml").write_text(existing)
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = _no_real_service(monkeypatch)
    ui = FakeUI(
        [
            ("confirm", False),    # don't overwrite
            ("confirm", True),     # start automatically after reboot
            ("confirm", True),     # apply
        ]
    )
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda **_kw: ui)
    args = argparse.Namespace(command="setup", repo=None)
    assert setup_cli.run(args) == 0
    assert (home / "config.yaml").read_text() == existing
    # The service is (re)installed on the kept-config path too.
    assert installed == [("telegram", True)]
    # The summary describes the config being kept, not a blank default state.
    summary = "\n".join(ui.messages)
    assert "qwen3:8b" in summary and "http://localhost:11434/v1" in summary
    assert "Allowed    [42, 43]" in summary
    assert "kept as-is" in summary


# ── Unattended setup (`lesysbot setup --yes`) ─────────────────────────────────
#
# The installer runs this with no terminal at all, so the contract under test is
# narrow and absolute: never read stdin, never leave a half-configured remote
# bot, never print a password.

def _unattended_args(**overrides):
    import argparse

    defaults = dict(command="setup", repo=None, yes=True,
                    reconfigure=False, skip_dashboard=True)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _hermetic(tmp_path, monkeypatch, home="home"):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LESYSBOT_SKIP_SERVICE", "1")
    for var in list(os.environ):
        if var.startswith("LESYSBOT_SETUP_"):
            monkeypatch.delenv(var, raising=False)
    return tmp_path / home


def test_autoui_answers_with_defaults_and_never_reads_stdin(monkeypatch):
    from lesysbot.setup.ui import AutoUI

    def explode(*_a, **_kw):
        raise AssertionError("unattended setup must never read stdin")

    monkeypatch.setattr("builtins.input", explode)
    ui = AutoUI()
    assert ui.interactive is False
    assert ui.unattended is True
    assert ui.menu("pick", ["a", "b", "c"], default=2) == 2
    assert ui.text("name", "fallback") == "fallback"
    assert ui.text("secret", "s3cret", secret=True) == "s3cret"
    assert ui.confirm_yn("really?", default=False) is False
    assert ui.confirm_yn("really?", default=True) is True


def test_make_ui_returns_autoui_only_when_asked(monkeypatch):
    from lesysbot.setup.ui import AutoUI, PlainUI, make_ui

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert isinstance(make_ui(unattended=True), AutoUI)
    plain = make_ui()
    assert isinstance(plain, PlainUI) and not isinstance(plain, AutoUI)


def test_unattended_writes_the_default_config(tmp_path, monkeypatch):
    from lesysbot.setup import cli as setup_cli
    from lesysbot.setup.wizard import DEFAULT_OLLAMA_MODEL

    home = _hermetic(tmp_path, monkeypatch)
    installed = _no_real_service(monkeypatch)

    assert setup_cli.run(_unattended_args()) == 0
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "cli"
    assert cfg["llm"]["model"] == DEFAULT_OLLAMA_MODEL
    assert cfg["llm"]["base_url"] == "http://localhost:11434/v1"
    assert cfg["llm"]["api_key"] == "ollama"
    # Autostart is the default: the point of the service is surviving a reboot.
    assert installed == [("cli", True)]


def test_unattended_reads_telegram_from_the_environment(tmp_path, monkeypatch):
    from lesysbot.setup import cli as setup_cli

    home = _hermetic(tmp_path, monkeypatch)
    _no_real_service(monkeypatch)
    monkeypatch.setenv("LESYSBOT_SETUP_PROVIDER", "telegram")
    monkeypatch.setenv("LESYSBOT_SETUP_TELEGRAM_TOKEN", "12345:fakeTokenNotReal")
    monkeypatch.setenv("LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS", " 42, 99 ")

    assert setup_cli.run(_unattended_args()) == 0
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "telegram"
    assert cfg["messaging"]["telegram"]["allowed_user_ids"] == [42, 99]
    assert cfg["messaging"]["telegram"]["token"] == "12345:fakeTokenNotReal"


@pytest.mark.parametrize(
    "env, expected_hint",
    [
        ({"LESYSBOT_SETUP_PROVIDER": "telegram"},
         "LESYSBOT_SETUP_TELEGRAM_TOKEN"),
        ({"LESYSBOT_SETUP_PROVIDER": "telegram",
          "LESYSBOT_SETUP_TELEGRAM_TOKEN": "t"},
         "LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS"),
        ({"LESYSBOT_SETUP_PROVIDER": "telegram",
          "LESYSBOT_SETUP_TELEGRAM_TOKEN": "t",
          "LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS": "not-a-number"},
         "LESYSBOT_SETUP_TELEGRAM_ALLOWED_IDS"),
        ({"LESYSBOT_SETUP_LLM": "openai"}, "LESYSBOT_SETUP_API_KEY"),
    ],
)
def test_unattended_aborts_naming_the_missing_variable(
    tmp_path, monkeypatch, capsys, env, expected_hint
):
    """A half-configured remote bot is worse than a failed install — and the
    message has to name the variable, because there is nobody to ask."""
    from lesysbot.setup import cli as setup_cli

    home = _hermetic(tmp_path, monkeypatch)
    _no_real_service(monkeypatch)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(SetupAborted):
        setup_cli.run(_unattended_args())
    assert expected_hint in capsys.readouterr().out
    assert not (home / "config.yaml").exists()


def test_unattended_keeps_an_existing_config_unless_reconfigured(tmp_path, monkeypatch):
    from lesysbot.setup import cli as setup_cli

    home = _hermetic(tmp_path, monkeypatch)
    home.mkdir(parents=True)
    existing = 'messaging:\n  provider: discord\nllm:\n  model: "kept-model"\n'
    (home / "config.yaml").write_text(existing)
    _no_real_service(monkeypatch)

    # Re-running the installer must not discard the answers given last time.
    assert setup_cli.run(_unattended_args()) == 0
    assert (home / "config.yaml").read_text() == existing

    assert setup_cli.run(_unattended_args(reconfigure=True)) == 0
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "cli"


def test_skip_dashboard_flag_sets_the_env_var(tmp_path, monkeypatch):
    from lesysbot.setup import cli as setup_cli

    _hermetic(tmp_path, monkeypatch)
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    _no_real_service(monkeypatch)
    seen = {}
    monkeypatch.setattr(apply_mod, "start_dashboard",
                        lambda ui, d, **_kw: seen.update(
                            skip=os.environ.get("LESYSBOT_SKIP_DASHBOARD")))

    assert setup_cli.run(_unattended_args(skip_dashboard=True)) == 0
    assert seen["skip"] == "1"


def test_skip_service_env_var_leaves_the_machine_alone(tmp_path, monkeypatch):
    """LESYSBOT_HOME does not relocate the LaunchAgent/systemd unit, so without
    this guard a scratch-home test would replace the real machine's service."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LESYSBOT_SKIP_SERVICE", "1")
    called = []
    for name in ("setup_service_linux", "setup_service_macos", "setup_service_windows"):
        monkeypatch.setattr(apply_mod, name,
                            lambda *a, **k: called.append(name))

    ui = FakeUI([])
    apply_mod.setup_service(ui, WizardState(), tmp_path)
    assert called == []
    assert any("LESYSBOT_SKIP_SERVICE" in m for m in ui.messages)


# ── Grafana credentials, unattended ───────────────────────────────────────────
def test_unattended_generates_a_grafana_password(tmp_path):
    """admin/admin on every install would be worse than no dashboard at all."""
    from lesysbot.setup.ui import AutoUI

    _url, user, password = apply_mod.ask_grafana_credentials(AutoUI(), tmp_path)
    assert user == "admin"
    assert len(password) >= 20
    assert password != "admin"
    assert password.isalnum()  # lands in a docker .env; nothing to quote


def test_unattended_reuses_a_previously_saved_password(tmp_path):
    """Grafana only honours GF_SECURITY_ADMIN_PASSWORD on an empty volume, so
    rotating it on a re-install would lock LeSysBot out of its own dashboard."""
    from lesysbot.setup.ui import AutoUI

    _u1, _user, first = apply_mod.ask_grafana_credentials(AutoUI(), tmp_path)
    apply_mod.write_grafana_env(tmp_path, "http://localhost:3000", "admin", first)

    _u2, _user2, second = apply_mod.ask_grafana_credentials(AutoUI(), tmp_path)
    assert second == first


def test_unattended_grafana_password_is_never_printed(tmp_path, monkeypatch):
    from lesysbot.setup.ui import AutoUI

    ui = AutoUI()
    printed = []
    monkeypatch.setattr(ui, "say", lambda text="", *_a, **_kw: printed.append(str(text)))
    monkeypatch.setattr(ui, "note", lambda text: printed.append(str(text)))
    monkeypatch.setattr(ui, "ok", lambda text: printed.append(str(text)))

    mon = tmp_path / "dashboard"
    mon.mkdir()
    _url, _user, password = apply_mod.ask_grafana_credentials(ui, tmp_path)
    apply_mod._persist_grafana(ui, tmp_path, mon, "http://localhost:3000", "admin", password)

    assert password not in "\n".join(printed)
    assert (tmp_path / "grafana.env").read_text().count(password) == 1


def test_generated_passwords_differ():
    from lesysbot.setup.unattended import generated_password

    assert generated_password() != generated_password()


# ── The allow-list parser shared by both modes ────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("42", ("42", "[42]")),
        ("42,99", ("42,99", "[42, 99]")),
        (" 42 , 99 ", ("42,99", "[42, 99]")),
        ("", None),
        ("abc", None),
        ("42,", None),
        ("42;99", None),
    ],
)
def test_parse_allowed_ids(raw, expected):
    assert wizard.parse_allowed_ids(raw) == expected
