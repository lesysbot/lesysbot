"""The setup wizard's step chain — state, navigation, and the summary menu.

The fresh-config wizard is a chain of numbered steps (LLM → messaging →
service). Each ``step_*`` fills one section of :class:`WizardState` and
remembers the answers, so revisiting a step offers them as defaults. Backing
out — a menu's "← Back" entry, or Esc at a text prompt — walks the chain one
step up (steps loop internally so a backed-out prompt re-shows that step's
menu). The summary is a menu whose "Change …" entries jump back into the
chain. Nothing is written until the summary's Apply; callers do that via
:mod:`lesysbot.setup.apply`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OLLAMA_MODEL = "llama3.2"


class SetupAborted(SystemExit):
    """Raised to abort setup with a message already printed."""


@dataclass
class WizardState:
    llm_choice: int = 1
    msg_choice: int = 1
    auto_choice: int = 1
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    msg_provider: str = "cli"
    tg_token: str = ""
    tg_raw_ids: str = ""
    tg_allowed_ids: str = "[]"
    slack_bot: str = ""
    slack_app: str = ""
    auto_start: bool = False
    # Every install gets the background service: it serves the control panel,
    # which is meant to be online whenever the machine is (and it runs the
    # Telegram/Slack bot too, when one is configured).
    needs_service: bool = True


# ── Ollama helpers ────────────────────────────────────────────────────────────
def ollama_models() -> list[str]:
    """Installed Ollama model names (empty if none / no server / no CLI)."""
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in out.splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name:
            names.append(name)
    return names


def ollama_pull(ui, model: str) -> None:
    ui.say(f"\n  Pulling [bold]{model}[/bold] … this can take a few minutes.\n")
    try:
        rc = subprocess.run(["ollama", "pull", model]).returncode
    except OSError:
        rc = 1
    if rc == 0:
        ui.ok(f"Pulled {model}")
    else:
        ui.warn(f"Could not pull {model} — you can do it later with: ollama pull {model}")


def select_ollama_model(ui) -> str | None:
    """Pick an installed Ollama model or pull one. ``None`` = user backed out."""
    if shutil.which("ollama") is None:
        ui.warn("Ollama CLI not found on PATH.")
        ui.note("Install it from https://ollama.com, then re-run.")
        ui.note("For now you can name a model to use once Ollama is available.")
        return ui.text("Model name", DEFAULT_OLLAMA_MODEL)

    models = ollama_models()
    if not models:
        ui.warn("No Ollama models are installed yet.")
        model = ui.text("Model to download now", DEFAULT_OLLAMA_MODEL)
        if model is None:
            return None
        ollama_pull(ui, model)
        return model

    options = [*models, "Pull a different model (enter a name)", "← Back — change the LLM backend"]
    choice = ui.menu("Choose an Ollama model", options, default=1)
    if choice == len(options):
        return None
    if choice == len(options) - 1:
        model = ui.text("Model name to pull (e.g. llama3.2, qwen3.5, gemma3:4b)", DEFAULT_OLLAMA_MODEL)
        if model is None:
            return None
        ollama_pull(ui, model)
        return model
    return models[choice - 1]


# ── Wizard steps ──────────────────────────────────────────────────────────────
def step_llm(ui, st: WizardState) -> None:
    # Loops so that backing out of a follow-up prompt (Esc, or the model
    # picker's ← Back) lands back on this step's menu, answers intact.
    while True:
        prev = st.llm_choice
        st.llm_choice = ui.menu(
            "Step 1 — LLM Backend",
            [
                "Ollama    — local, recommended (no API key needed)",
                "OpenAI    — cloud API",
                "vLLM      — self-hosted OpenAI-compatible server",
                "Custom    — any OpenAI-compatible endpoint",
            ],
            default=st.llm_choice,
        )
        # Previous answers are offered again only while the backend is
        # unchanged — a gpt-4o default under vLLM would just mislead.
        if st.llm_choice != prev:
            st.llm_base_url = st.llm_model = st.llm_api_key = ""

        if st.llm_choice == 2:
            st.llm_base_url = "https://api.openai.com/v1"
            model = ui.text("Model", st.llm_model or "gpt-4o")
            if model is None:
                continue
            st.llm_model = model
            key = ui.text("API key (sk-...)", st.llm_api_key)
            if key is None:
                continue
            st.llm_api_key = key
        elif st.llm_choice == 3:
            url = ui.text("vLLM base URL", st.llm_base_url or "http://localhost:8000/v1")
            if url is None:
                continue
            st.llm_base_url = url
            model = ui.text("Model", st.llm_model or "meta-llama/Llama-3.2-8B-Instruct")
            if model is None:
                continue
            st.llm_model = model
            st.llm_api_key = "vllm"
        elif st.llm_choice == 4:
            url = ui.text("Base URL", st.llm_base_url or "http://localhost:8000/v1")
            if url is None:
                continue
            st.llm_base_url = url
            model = ui.text("Model", st.llm_model or "llama3.2")
            if model is None:
                continue
            st.llm_model = model
            key = ui.text("API key", st.llm_api_key or "none")
            if key is None:
                continue
            st.llm_api_key = key
        else:  # 1 — Ollama
            st.llm_base_url = "http://localhost:11434/v1"
            model = select_ollama_model(ui)
            if model is None:
                continue
            st.llm_model = model
            st.llm_api_key = "ollama"
        return


def step_messaging(ui, st: WizardState) -> bool:
    """Returns True to continue, False to go back to the LLM step."""
    while True:
        ui.say("\n  You can always chat in this terminal with [bold]lesysbot --provider cli[/bold].")
        ui.say("  Add Telegram or Slack to also message LeSysBot remotely.\n")
        choice = ui.menu(
            "Step 2 — How to reach LeSysBot",
            [
                "Terminal only (default)",
                "Telegram",
                "Slack",
                "← Back — change the LLM backend",
            ],
            default=st.msg_choice,
        )
        if choice == 4:
            return False
        st.msg_choice = choice

        if choice == 2:
            st.msg_provider = "telegram"
            token = ui.text("Bot token (from @BotFather)", st.tg_token)
            if token is None:
                continue
            st.tg_token = token
            ui.note("Find your numeric ID by messaging @userinfobot on Telegram.")
            # An explicit allow-list is required — with an empty list, ANY
            # Telegram user who finds the bot can drive tools on this machine.
            backed_out = False
            while True:
                raw = ui.text("Allowed Telegram user IDs, comma-separated", st.tg_raw_ids)
                if raw is None:
                    backed_out = True
                    break
                raw = re.sub(r"\s", "", raw)
                if re.fullmatch(r"[0-9]+(,[0-9]+)*", raw):
                    st.tg_raw_ids = raw
                    st.tg_allowed_ids = "[" + ", ".join(raw.split(",")) + "]"
                    break
                if ui.eof:
                    # Piped input that has run dry can never satisfy this loop.
                    ui.say("  [red]✗[/red]  Input ended before a Telegram user ID was given "
                           "— an allow-list is required.")
                    raise SetupAborted(1)
                ui.warn("Enter at least one numeric user ID (e.g. 123456789) "
                        "— the bot must not be open to everyone.")
            if backed_out:
                continue
        elif choice == 3:
            st.msg_provider = "slack"
            bot = ui.text("Bot token (xoxb-...)", st.slack_bot)
            if bot is None:
                continue
            st.slack_bot = bot
            app = ui.text("App token (xapp-...)", st.slack_app)
            if app is None:
                continue
            st.slack_app = app
        else:
            st.msg_provider = "cli"
        return True


def step_autostart(ui, st: WizardState) -> bool:
    """Returns True to continue, False to go back to the messaging step."""
    # Always a service: the control panel (settings, tools, health) is meant to
    # be reachable at any time, not only while a terminal happens to be open.
    st.needs_service = True
    if st.msg_provider in ("telegram", "slack"):
        ui.say(f"\n  LeSysBot runs in the background as a service — it keeps the "
               f"control panel online and answers your {st.msg_provider} messages.\n")
    else:
        ui.say("\n  LeSysBot runs in the background as a service so the control panel "
               "(settings, tools, health) stays online.\n")
    when = "at login" if sys.platform == "win32" else "after reboot"
    choice = ui.menu(
        "Step 3 — Service",
        [
            f"Start now and automatically {when} (recommended)",
            f"Start now only — not {when}",
            "← Back — change how to reach LeSysBot",
        ],
        default=st.auto_choice,
    )
    if choice == 3:
        return False
    st.auto_choice = choice
    st.auto_start = choice == 1
    return True


def run_steps(ui, st: WizardState, start: int) -> None:
    """Walk the wizard chain from *start*; ← Back moves one step up."""
    step = start
    while step != 0:
        if step == 1:
            step_llm(ui, st)
            step = 2
        elif step == 2:
            step = 3 if step_messaging(ui, st) else 1
        elif step == 3:
            step = 0 if step_autostart(ui, st) else 2


def show_summary(ui, st: WizardState, data_dir: Path) -> None:
    startup = ("service — starts now and at reboot" if st.auto_start
               else "service — starts now, not at reboot")
    ui.say("\n  [bold]Summary[/bold]\n")
    ui.say(f"  LLM        {st.llm_model}  ({st.llm_base_url})")
    ui.say(f"  Provider   {st.msg_provider}")
    if st.msg_provider == "telegram":
        ui.say(f"  Allowed    {st.tg_allowed_ids}")
    ui.say(f"  Startup    {startup}")
    ui.say(f"  Config     {data_dir / 'config.yaml'}")
    ui.say(f"  Working    {data_dir}")
    ui.say("")


def step_summary(ui, st: WizardState, data_dir: Path) -> bool:
    """Returns True once the user applies, False to quit without writing."""
    while True:
        show_summary(ui, st, data_dir)
        options = ["Apply these settings", "Change LLM backend", "Change how to reach LeSysBot",
                   "Change startup behaviour"]
        startup_opt = 4
        options.append("Quit — exit without writing config")
        quit_opt = len(options)
        choice = ui.menu("Ready?", options, default=1)
        if choice == 1:
            return True
        if choice == 2:
            step_llm(ui, st)
        elif choice == 3:
            run_steps(ui, st, 2)  # messaging decides whether the service step applies
        elif choice == startup_opt:
            run_steps(ui, st, 3)
        elif choice == quit_opt:
            return False
