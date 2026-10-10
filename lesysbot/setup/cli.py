"""`lesysbot setup` — argument wiring and the top-level setup flow.

The install scripts bootstrap (find/instal a Python, build the venv, install the
package) and then run ``lesysbot setup --yes``; it also runs standalone at any
time to reconfigure an existing install. Flow: fresh config → wizard chain +
summary (nothing written until Apply); existing config kept → only the autostart
question. Then bundled-tools seeding (never clobbers) and platform service setup
— installed for every setup, because the service is what keeps the control panel
online.

``--yes`` is the unattended mode the installer uses: answers come from defaults
and ``LESYSBOT_SETUP_*`` (see :mod:`lesysbot.setup.unattended`) instead of
prompts, and :class:`~lesysbot.setup.ui.AutoUI` guarantees stdin is never read.
Everything after the answers is the same code either way.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from lesysbot.core.paths import user_dir


def register_subcommand(subparsers: argparse._SubParsersAction) -> None:
    setup = subparsers.add_parser(
        "setup",
        help="Change the model, Telegram/Discord, and startup settings",
    )
    setup.add_argument(
        "--repo",
        default=None,
        help="Seed bundled content from this checkout instead of the installed "
             "copy (for development; not needed for a normal install)",
    )
    setup.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Unattended: take every default (and any LESYSBOT_SETUP_* overrides) "
             "without prompting — what the installer runs",
    )
    setup.add_argument(
        "--reconfigure",
        action="store_true",
        help="With --yes, replace an existing config.yaml instead of keeping it",
    )
    setup.add_argument(
        "--skip-dashboard",
        action="store_true",
        help="Don't set up the Grafana dashboard (same as LESYSBOT_SKIP_DASHBOARD=1)",
    )


def run(args: argparse.Namespace) -> int:
    """Entry point — runs the flow, turning Ctrl-C into a clean exit.

    Ctrl-C is a normal way to leave a wizard (the raw-mode key reader turns
    ``\\x03`` into ``KeyboardInterrupt`` so menus stay escapable), and nothing
    above this catches it for the setup path — so it used to end in a traceback
    that reads like a crash.
    """
    from lesysbot.setup.ui import make_ui

    ui = make_ui(unattended=getattr(args, "yes", False))
    try:
        return _flow(ui, args)
    except KeyboardInterrupt:
        ui.say("\n\n  [yellow]Setup cancelled.[/yellow]")
        ui.note("Nothing further was changed — re-run `lesysbot setup` anytime.")
        return 130


def _flow(ui, args: argparse.Namespace) -> int:
    from lesysbot.setup import apply, wizard

    unattended = getattr(args, "yes", False)
    if getattr(args, "skip_dashboard", False):
        # One knob, two spellings: the flag and the env var the dashboard step
        # already honours (and that callers such as CI set directly).
        os.environ["LESYSBOT_SKIP_DASHBOARD"] = "1"

    data_dir = user_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = Path(args.repo).resolve() if getattr(args, "repo", None) else None
    config_file = data_dir / "config.yaml"

    ui.say("\n  [bold]LeSysBot Setup[/bold]")
    ui.say("  " + "─" * 50)

    keep_config = False
    if config_file.exists():
        ui.say("")
        if unattended:
            # Re-running the installer must not silently discard the answers
            # someone gave last time — everything below (tools, dashboard,
            # service) is still refreshed.
            keep_config = not getattr(args, "reconfigure", False)
            ui.note("Keeping existing config.yaml (--reconfigure replaces it)."
                    if keep_config else "Replacing config.yaml (--reconfigure).")
        else:
            keep_config = not ui.confirm_yn(
                f"{config_file} already exists — overwrite with new settings?", default=False
            )
            if keep_config:
                ui.note("Keeping existing config.yaml.")

    if not keep_config:
        # Fresh config: LLM → messaging → service steps with back/forward
        # navigation, then a summary menu that can jump back into any step.
        # config.yaml is only written once the summary's Apply is chosen.
        if unattended:
            from lesysbot.setup import unattended as auto

            st = auto.state_from_env()
            wizard.show_summary(ui, st, data_dir)
        else:
            st = wizard.WizardState()
            wizard.run_steps(ui, st, 1)
            if not wizard.step_summary(ui, st, data_dir):
                ui.say("\n  [yellow]Aborted — nothing was written.[/yellow]")
                ui.note("(The lesysbot package itself remains installed — re-run `lesysbot setup` anytime.)")
                return 0
        provider = st.msg_provider
        needs_service = st.needs_service
        apply.write_config(st, data_dir)
        ui.ok(f"config.yaml written to {config_file}")
    else:
        # Existing config kept — read it back so the summary describes the
        # install being kept (LLM, provider, allow-list) instead of a blank
        # default state. The background service is installed either way (it
        # serves the control panel), so only the autostart question applies
        # here; no step navigation.
        st = apply.read_config_state(config_file)
        provider = st.msg_provider
        needs_service = st.needs_service = True
        ui.say("\n  LeSysBot runs in the background as a service so the control panel "
               "stays online.\n")
        st.auto_start = (
            True if unattended
            else ui.confirm_yn("Start LeSysBot automatically after reboot?", default=True)
        )

        wizard.show_summary(ui, st, data_dir, config_kept=True)
        if not unattended and not ui.confirm_yn("Apply these settings?", default=True):
            ui.say("\n  [yellow]Aborted.[/yellow]")
            return 0

    if apply.seed_tools(repo_dir, data_dir):
        ui.ok(f"tools installed in {data_dir / 'tools'}")

    if apply.seed_dashboard(repo_dir, data_dir):
        # "installed/updated", not "copied": on a re-run this is how a fix to the
        # stack's scripts or dashboards actually reaches an existing install.
        ui.ok(f"dashboard stack installed/updated in {data_dir / 'dashboard'}")
    if apply.seed_dashboards(repo_dir, data_dir):
        ui.ok("dashboards installed")
    if apply.seed_catalog(repo_dir, data_dir):
        ui.ok("marketplace catalog installed — browse it with `lesysbot search`")

    ui.say("")
    apply.setup_service(ui, st, data_dir)

    # The Grafana dashboard ships with LeSysBot — bring it up as part of setup
    # (idempotent; no-ops when already running). Never optional, but never fatal:
    # a machine without Docker gets clear finish-it instructions, not a failure.
    apply.start_dashboard(ui, data_dir)

    apply.print_epilogue(ui, provider, needs_service, data_dir)
    return 0
