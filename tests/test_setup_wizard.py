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

from lesysbot.setup import apply as apply_mod
from lesysbot.setup import wizard
from lesysbot.setup.wizard import SetupAborted, WizardState

DEFAULT = object()  # scripted answer meaning "accept the offered default"


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
    assert (st.llm_model, st.llm_base_url) == ("llama3.2", "http://localhost:11434/v1")
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
    # Never clobber an existing tools dir on re-install.
    assert apply_mod.seed_tools(repo, data) is False
    assert apply_mod.seed_tools(None, data) is False


def _fake_monitoring(data_dir: Path) -> Path:
    """A minimal seeded monitoring/ dir with a start script, for start tests."""
    mon = data_dir / "monitoring"
    (mon / "scripts").mkdir(parents=True)
    (mon / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (mon / "scripts" / "start.ps1").write_text("")
    return mon


def test_seed_monitoring_copies_once_and_skips_runtime(tmp_path):
    repo = tmp_path / "repo"
    (repo / "monitoring" / "scripts").mkdir(parents=True)
    (repo / "monitoring" / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "monitoring" / ".env.example").write_text("GRAFANA_PORT=3000\n")
    (repo / "monitoring" / "bin").mkdir()          # downloaded exporter binaries
    (repo / "monitoring" / "bin" / "node_exporter").write_text("ELF")
    (repo / "monitoring" / "__pycache__").mkdir()
    data = tmp_path / "home"
    data.mkdir()
    assert apply_mod.seed_monitoring(repo, data) is True
    assert (data / "monitoring" / "scripts" / "start.sh").exists()
    assert not (data / "monitoring" / "bin").exists()        # runtime dir skipped
    assert not (data / "monitoring" / "__pycache__").exists()
    assert (data / "monitoring" / ".env").read_text() == "GRAFANA_PORT=3000\n"  # seeded
    # Never clobber an existing copy on re-install; None repo is a no-op.
    assert apply_mod.seed_monitoring(repo, data) is False
    assert apply_mod.seed_monitoring(None, data) is False


def test_start_monitoring_env_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_SKIP_MONITORING", "1")
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    _fake_monitoring(tmp_path)
    runner = Recorder(returncode=0)
    assert apply_mod.start_monitoring(FakeUI([]), tmp_path, runner=runner) is False
    assert runner.calls == []  # skipped before any docker call


def test_start_monitoring_no_dir_is_noop(tmp_path):
    runner = Recorder(returncode=0)
    assert apply_mod.start_monitoring(FakeUI([]), tmp_path, runner=runner) is False
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


def _ran_stack(runner) -> bool:
    return any(c and c[0] == "bash" and "start" in " ".join(c) for c in runner.calls)


# Every start_monitoring path first asks the Grafana username + password; accept
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
    mon = _fake_monitoring(tmp_path)
    (mon / ".env").write_text("GRAFANA_PORT=3001\n", encoding="utf-8")
    assert apply_mod.monitoring_port(mon) == "3001"
    assert apply_mod.default_grafana_url(tmp_path) == "http://localhost:3001"

    apply_mod.write_grafana_env(tmp_path, "http://localhost:3000", "bob", "pw-123456789")
    assert apply_mod.default_grafana_url(tmp_path) == "http://localhost:3001"
    assert apply_mod.ask_grafana_credentials(FakeUI(CREDS), tmp_path)[0] == "http://localhost:3001"

    # a remote Grafana is a deliberate choice — keep it
    apply_mod.write_grafana_env(tmp_path, "http://gf.example:3000", "bob", "pw-123456789")
    assert apply_mod.default_grafana_url(tmp_path) == "http://gf.example:3000"

    # no/garbled GRAFANA_PORT → the documented default
    (mon / ".env").write_text("GRAFANA_PORT=\n", encoding="utf-8")
    assert apply_mod.monitoring_port(mon) == "3000"


def test_start_monitoring_saves_grafana_env_and_docker_env(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    mon = _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=True)
    # Way (menu) first, then the Grafana username + password.
    ui = FakeUI([("menu", 1), ("text", "bob"), ("text", "pw-123456789")])
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is True
    from lesysbot.core.paths import parse_env_file

    saved = parse_env_file(tmp_path / "grafana.env")
    assert (saved["LESYSBOT_GRAFANA_USER"], saved["LESYSBOT_GRAFANA_PASSWORD"]) == (
        "bob", "pw-123456789")
    # The bundled Docker Grafana is pointed at the same admin login.
    docker_env = (mon / ".env").read_text()
    assert "GRAFANA_ADMIN_USER=bob" in docker_env
    assert "GRAFANA_ADMIN_PASSWORD=pw-123456789" in docker_env


# ── Linux: ask auto-start vs. manual (when Docker is running) ──────────────────
def test_start_monitoring_linux_auto_start(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=True)
    ui = FakeUI([("menu", 1), *CREDS])  # way first, then login
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is True
    assert _ran_stack(runner)


def test_start_monitoring_linux_manual_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=True)
    ui = FakeUI([("menu", 2), *CREDS])  # way first (manual), then login
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)  # nothing started; just told how


def test_start_monitoring_linux_docker_not_installed(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_monitoring(tmp_path)
    runner = DockerRunner()
    ui = FakeUI([*CREDS])  # no menu asked when Docker isn't ready
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)
    assert _said(ui, "docker.com/engine/install")
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)  # native-Grafana alternative offered


def test_start_monitoring_linux_daemon_down(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "linux")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)
    assert _said(ui, "daemon isn't reachable")


# ── macOS / Windows: warn + instruct native Grafana ───────────────────────────
def test_start_monitoring_macos_instructs_native_grafana(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])  # never asks a menu on macOS/Windows
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)          # how to install Grafana
    assert _said(ui, "LESYSBOT_GRAFANA_URL")              # how to connect it


def test_start_monitoring_macos_with_docker_mentions_shortcut(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr(apply_mod.sys, "platform", "darwin")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=True)  # Docker running → mention the shortcut
    ui = FakeUI([*CREDS])
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
    assert not _ran_stack(runner)  # still doesn't auto-run on macOS/Windows
    assert _said(ui, apply_mod.GRAFANA_DOWNLOAD)
    assert _said(ui, "start.sh")   # the bundled-stack shortcut command


def test_start_monitoring_windows_instructs(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(apply_mod.sys, "platform", "win32")
    _fake_monitoring(tmp_path)
    runner = DockerRunner(daemon_up=False)
    ui = FakeUI([*CREDS])
    assert apply_mod.start_monitoring(ui, tmp_path, runner=runner) is False
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
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda: ui)
    args = argparse.Namespace(command="setup", repo=None)
    assert setup_cli.run(args) == 0
    cfg = yaml.safe_load((tmp_path / "home" / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "cli"
    assert cfg["llm"]["model"] == "m1"
    # Even a terminal-only install gets the service — it serves the control panel.
    assert installed == [("cli", False)]


def test_cli_run_seeds_and_attempts_monitoring(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    # A repo checkout with a monitoring/ stack to seed from.
    repo = tmp_path / "repo"
    (repo / "monitoring" / "scripts").mkdir(parents=True)
    (repo / "monitoring" / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "monitoring" / ".env.example").write_text("GRAFANA_PORT=3000\n")

    home = tmp_path / "home"
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LESYSBOT_SKIP_MONITORING", raising=False)
    _no_real_service(monkeypatch)
    # Docker not ready → start_monitoring only prints instructions (no subprocess).
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: None)
    # LLM (custom) → messaging (terminal) → service → summary Apply → Grafana login.
    ui = FakeUI([*custom_llm_answers(), ("menu", 1), ("menu", 1), ("menu", 1),
                 ("text", DEFAULT), ("text", DEFAULT)])
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda: ui)
    args = argparse.Namespace(command="setup", repo=str(repo))
    assert setup_cli.run(args) == 0
    # The dashboard stack was seeded into the installed home as a standard part.
    assert (home / "monitoring" / "scripts" / "start.sh").exists()
    assert (home / "monitoring" / ".env").exists()
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
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda: ui)
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
