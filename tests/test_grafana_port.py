"""Choosing Grafana's port when another program already holds it.

Grafana runs on the host network and binds ``127.0.0.1:<GRAFANA_PORT>``; when
something else listens there the container crash-loops on "address already in
use" and the dashboard just never appears. 3000 is every dev server's default,
so the stack has to notice and move — in ``start.sh`` (which every start path
runs) and in the setup wizard (which saves the URL before the stack starts).

What's pinned: a port held by *another* program moves Grafana to the next free
one and the move is saved; a port held by *our own* running Grafana is left
alone; an explicit choice is honoured or refused, never silently swapped.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lesysbot.core import grafana
# Imported at module load, before conftest's autouse fixture swaps the
# attribute for an always-free stub — this is the real kernel check.
from lesysbot.core.grafana import port_in_use as real_port_in_use
from lesysbot.core.paths import parse_env_file
from lesysbot.setup import apply as apply_mod

SCRIPT = Path(__file__).resolve().parents[1] / "dashboard" / "scripts" / "start.sh"


def _busy(*ports):
    taken = {str(p) for p in ports}
    return lambda port, host="127.0.0.1": str(port) in taken


def _inspect(stdout="", rc=0):
    """A runner standing in for ``docker inspect lesysbot-grafana``."""
    return lambda cmd, **_kw: SimpleNamespace(returncode=rc, stdout=stdout, stderr="")


def _stack(tmp_path, port="3000", prom="9090") -> Path:
    mon = tmp_path / "dashboard"
    mon.mkdir()
    (mon / ".env").write_text(
        f"# keep me\nGRAFANA_ADMIN_USER=admin\nGRAFANA_PORT={port}\nPROM_PORT={prom}\n"
    )
    return mon


# ── the kernel check ──────────────────────────────────────────────────────────
def test_port_in_use_sees_a_real_listener():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert real_port_in_use(port) is True
    assert real_port_in_use(port) is False


# ── whose port is it? ─────────────────────────────────────────────────────────
def test_our_grafana_port_reads_the_running_container():
    out = "true false PATH=/usr/bin GF_SERVER_HTTP_PORT=3005 GF_SERVER_HTTP_ADDR=127.0.0.1\n"
    assert grafana.our_grafana_port(_inspect(out)) == "3005"


def test_a_crash_looping_container_holds_no_port():
    """Restarting = it failed to bind, usually on exactly this conflict."""
    out = "true true GF_SERVER_HTTP_PORT=3000\n"
    assert grafana.our_grafana_port(_inspect(out)) is None


def test_no_container_or_no_docker_means_not_ours():
    assert grafana.our_grafana_port(_inspect(rc=1)) is None

    def no_docker(*_a, **_kw):
        raise FileNotFoundError("docker")

    assert grafana.our_grafana_port(no_docker) is None


def test_conflict_only_when_the_holder_is_not_us(monkeypatch):
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    ours = _inspect("true false GF_SERVER_HTTP_PORT=3000")
    assert grafana.grafana_port_conflict("3000", ours) is False
    assert grafana.grafana_port_conflict("3000", _inspect(rc=1)) is True
    assert grafana.grafana_port_conflict("3001", _inspect(rc=1)) is False


def test_next_free_port_skips_taken_and_avoided(monkeypatch):
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000, 3001))
    assert grafana.next_free_port(3000, avoid=("3002",)) == "3003"
    monkeypatch.setattr(grafana, "port_in_use", lambda *_a, **_k: True)
    assert grafana.next_free_port(3000, span=5) is None


# ── persisting the choice ─────────────────────────────────────────────────────
def test_set_stack_env_edits_one_line_and_keeps_the_rest(tmp_path):
    mon = _stack(tmp_path)
    grafana.set_stack_env(mon, "GRAFANA_PORT", "3001")
    text = (mon / ".env").read_text()
    assert "GRAFANA_PORT=3001" in text and "GRAFANA_PORT=3000" not in text
    assert "# keep me" in text and "PROM_PORT=9090" in text
    grafana.set_stack_env(mon, "NEW_KEY", "x")
    assert parse_env_file(mon / ".env")["NEW_KEY"] == "x"


def test_sync_saved_url_follows_the_stack_but_not_a_remote_grafana(tmp_path):
    mon = _stack(tmp_path, port="3001")
    env = tmp_path / "grafana.env"
    env.write_text("LESYSBOT_GRAFANA_URL=http://localhost:3000\nLESYSBOT_GRAFANA_USER=a\n")
    assert grafana.sync_saved_url(mon, env) == "http://localhost:3001"
    assert parse_env_file(env) == {
        "LESYSBOT_GRAFANA_URL": "http://localhost:3001", "LESYSBOT_GRAFANA_USER": "a",
    }
    assert grafana.sync_saved_url(mon, env) is None  # already right

    env.write_text("LESYSBOT_GRAFANA_URL=http://grafana.lan:3000\n")
    assert grafana.sync_saved_url(mon, env) is None
    assert "grafana.lan:3000" in env.read_text()


# ── the setup wizard ──────────────────────────────────────────────────────────
class _UI:
    def __init__(self, answers=(), interactive=True):
        self.answers = list(answers)
        self.interactive = interactive
        self.prompts = []
        self.messages = []

    def text(self, prompt, default="", secret=False):
        self.prompts.append((prompt, default))
        return self.answers.pop(0) if self.answers else default

    def say(self, text="", *_a, **_kw):
        self.messages.append(str(text))

    note = ok = warn = say


def test_wizard_offers_the_next_free_port(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    mon = _stack(tmp_path)
    ui = _UI()
    assert apply_mod.choose_grafana_port(ui, mon, _inspect(rc=1)) == "3001"
    assert ui.prompts == [("Port for Grafana", "3001")]
    assert parse_env_file(mon / ".env")["GRAFANA_PORT"] == "3001"


def test_wizard_rejects_a_typed_port_that_is_also_taken(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000, 8080))
    mon = _stack(tmp_path)
    ui = _UI(answers=["8080", "8081"])
    assert apply_mod.choose_grafana_port(ui, mon, _inspect(rc=1)) == "8081"
    assert len(ui.prompts) == 2


def test_unattended_wizard_moves_without_asking(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    mon = _stack(tmp_path)
    ui = _UI(interactive=False)
    assert apply_mod.choose_grafana_port(ui, mon, _inspect(rc=1)) == "3001"
    assert ui.prompts == []


def test_wizard_never_lands_on_prometheus_port(tmp_path, monkeypatch):
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    mon = _stack(tmp_path, prom="3001")
    assert apply_mod.choose_grafana_port(_UI(interactive=False), mon, _inspect(rc=1)) == "3002"


def test_wizard_leaves_our_own_running_grafana_alone(tmp_path, monkeypatch):
    """Re-running setup on a working stack must not 'fix' it onto another port."""
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    mon = _stack(tmp_path)
    ui = _UI()
    ours = _inspect("true false GF_SERVER_HTTP_PORT=3000")
    assert apply_mod.choose_grafana_port(ui, mon, ours) == "3000"
    assert ui.prompts == []
    assert parse_env_file(mon / ".env")["GRAFANA_PORT"] == "3000"


def test_setup_env_var_picks_the_port(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_SETUP_GRAFANA_PORT", "3333")
    mon = _stack(tmp_path)
    assert apply_mod.choose_grafana_port(_UI(interactive=False), mon, _inspect(rc=1)) == "3333"
    assert parse_env_file(mon / ".env")["GRAFANA_PORT"] == "3333"


def test_saved_url_names_the_moved_port(tmp_path, monkeypatch):
    """The point of choosing in the wizard: the URL it saves is the real one."""
    monkeypatch.delenv("LESYSBOT_SETUP_GRAFANA_PORT", raising=False)
    monkeypatch.delenv("LESYSBOT_SKIP_DASHBOARD", raising=False)
    monkeypatch.setattr(grafana, "port_in_use", _busy(3000))
    monkeypatch.setattr(apply_mod.shutil, "which", lambda _: "/usr/bin/docker")
    mon = _stack(tmp_path)
    (mon / "scripts").mkdir()
    (mon / "scripts" / "start.sh").write_text("#!/usr/bin/env bash\n")

    def runner(cmd, **_kw):
        rc = 1 if cmd[:2] == ["docker", "inspect"] else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    from lesysbot.setup.ui import AutoUI

    apply_mod.start_dashboard(AutoUI(), tmp_path, runner=runner)
    saved = parse_env_file(tmp_path / "grafana.env")
    assert saved["LESYSBOT_GRAFANA_URL"] == "http://localhost:3001"


# ── start.sh ──────────────────────────────────────────────────────────────────
pytest_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _start_sh(tmp_path, *, port="3000", busy=(), ours="", want=""):
    """Source start.sh in a scratch stack dir and run choose_grafana_port.

    ``port_busy`` and ``our_grafana_port`` are the two machine facts, so they
    are overridden after sourcing — the rest is the real script.
    """
    mon = _stack(tmp_path, port=port)
    busy_cases = " ".join(str(p) for p in busy) or "none"
    script = f"""
      set -euo pipefail
      source {SCRIPT}
      cd {mon}
      PORT="$(env_get GRAFANA_PORT)"
      port_busy() {{ local b; for b in {busy_cases}; do [ "$b" = "$1" ] && return 0; done; return 1; }}
      our_grafana_port() {{ printf '%s' '{ours}'; }}
      choose_grafana_port '{want}'
      echo "PORT=$PORT"
    """
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r, parse_env_file(mon / ".env")


@pytest_bash
def test_start_sh_moves_grafana_off_a_taken_port(tmp_path):
    r, env = _start_sh(tmp_path, busy=(3000, 3001))
    assert r.returncode == 0, r.stderr
    assert "PORT=3002" in r.stdout and "used by another program" in r.stdout
    assert env["GRAFANA_PORT"] == "3002"
    assert env["GRAFANA_ADMIN_USER"] == "admin"  # rest of .env untouched


@pytest_bash
def test_start_sh_keeps_a_free_port(tmp_path):
    r, env = _start_sh(tmp_path)
    assert r.returncode == 0 and "PORT=3000" in r.stdout
    assert env["GRAFANA_PORT"] == "3000"


@pytest_bash
def test_start_sh_keeps_the_port_our_grafana_holds(tmp_path):
    r, env = _start_sh(tmp_path, busy=(3000,), ours="3000")
    assert r.returncode == 0 and "PORT=3000" in r.stdout
    assert env["GRAFANA_PORT"] == "3000"


@pytest_bash
def test_start_sh_explicit_port_is_used(tmp_path):
    r, env = _start_sh(tmp_path, want="4000")
    assert r.returncode == 0 and "PORT=4000" in r.stdout
    assert env["GRAFANA_PORT"] == "4000"


@pytest_bash
def test_start_sh_explicit_taken_port_is_refused_not_swapped(tmp_path):
    r, env = _start_sh(tmp_path, busy=(4000,), want="4000")
    assert r.returncode != 0 and "already used by another program" in r.stderr
    assert env["GRAFANA_PORT"] == "3000"


@pytest_bash
def test_start_sh_rejects_a_non_number(tmp_path):
    r, _ = _start_sh(tmp_path, want="abc")
    assert r.returncode != 0 and "port number" in r.stderr


# ── lesysbot dashboard start --grafana-port ───────────────────────────────────
def test_cli_passes_the_port_to_start_sh(tmp_path, monkeypatch):
    from lesysbot.cli import dashboard as dash_cli

    seen = []
    monkeypatch.setattr(dash_cli, "_stack_script",
                        lambda ctx, action, *extra: seen.append((action, extra)) or 0)
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    ctx = SimpleNamespace(settings=SimpleNamespace(config_dir=tmp_path),
                          console=SimpleNamespace(print=lambda *_a, **_k: None))
    assert dash_cli._start(ctx, SimpleNamespace(grafana_port="3333")) == 0
    assert dash_cli._start(ctx, SimpleNamespace(grafana_port=None)) == 0
    assert seen == [("up", ("--grafana-port", "3333")), ("up", ())]
