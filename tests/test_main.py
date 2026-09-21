"""Entry-point helpers (lesysbot/__main__.py)."""
from __future__ import annotations

import pytest


# ── `lesysbot chat` ───────────────────────────────────────────────────────────
#
# `chat` is deliberately not a new code path: main() rewrites it to
# `--provider cli` and everything downstream stays unaware it exists. These
# tests pin that, because the alternative (a branch of its own) is what would
# quietly skip the singleton guard or the interactive-logging rules.

def _normalize(argv):
    """Parse *argv* and apply main()'s `chat` rewrite, returning the namespace."""
    from lesysbot.__main__ import build_parser

    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "chat":
        if getattr(args, "provider", None) not in (None, "cli"):
            build_parser().error("conflicting --provider")
        args.provider = "cli"
    return args


def test_chat_is_provider_cli():
    args = _normalize(["chat"])
    assert args.command == "chat"
    assert args.provider == "cli"


def test_chat_runs_the_bot_but_is_not_the_service():
    from lesysbot.__main__ import _runs_the_bot

    args = _normalize(["chat"])
    assert _runs_the_bot(args.command, args) is True
    # `service` is `command == "run"` — false here, so no control panel is
    # started and the singleton guard is skipped: a chat may run alongside the
    # background service, which is the whole point of having both.
    assert (args.command == "run") is False


def test_bare_lesysbot_still_prints_status():
    from lesysbot.__main__ import _runs_the_bot

    args = _normalize([])
    assert args.command is None
    assert _runs_the_bot(args.command, args) is False


def test_chat_is_not_dispatched_by_the_management_cli():
    """cli.handles() owns the verbs that exit before any bot setup; `chat` must
    fall through to the bot path instead."""
    from lesysbot.cli import handles

    assert handles("chat") is False
    assert handles("setup") is True


def test_chat_accepts_the_same_overrides_as_the_root_flags():
    args = _normalize(["chat", "--model", "llama3.2", "--base-url", "http://x:1/v1"])
    assert args.model == "llama3.2"
    assert args.base_url == "http://x:1/v1"


def test_chat_rejects_a_conflicting_provider():
    with pytest.raises(SystemExit):
        _normalize(["--provider", "telegram", "chat"])


def test_setup_yes_is_parseable():
    """The installer's exact invocation — a typo here breaks every install."""
    from lesysbot.__main__ import build_parser

    args = build_parser().parse_args(["setup", "--yes"])
    assert args.command == "setup" and args.yes is True
    args = build_parser().parse_args(
        ["setup", "--yes", "--repo", "/tmp/x", "--skip-dashboard", "--reconfigure"])
    assert args.repo == "/tmp/x" and args.skip_dashboard and args.reconfigure
