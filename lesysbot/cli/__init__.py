"""The `lesysbot` command line: parser construction and verb dispatch.

Split out of ``__main__`` so the bot's runtime and its CLI surface stop sharing
a 470-line module. ``__main__.main()`` is still the console-script entry point;
it asks here for the parser and for who handles a given command.

Verb modules are imported lazily inside :func:`dispatch`, so `lesysbot --provider
cli` doesn't pay for the marketplace, and a syntax error in a rarely used verb
can't stop the bot from starting.
"""

from __future__ import annotations

import argparse

# Commands handled entirely by this package, and the module that owns each.
_ARTIFACT_VERBS = {"install", "update", "list", "info", "remove", "enable", "disable"}
_HANDLERS = {
    **{verb: "lesysbot.cli.artifacts" for verb in _ARTIFACT_VERBS},
    "search": "lesysbot.cli.search",
    "doctor": "lesysbot.cli.doctor",
    "dashboard": "lesysbot.cli.dashboard",
    "setup": "lesysbot.setup.cli",
}


def register_all(subparsers: argparse._SubParsersAction) -> None:
    """Add every CLI verb to *subparsers*.

    Registration is eager (argparse needs the whole grammar up front to build
    `--help`), unlike dispatch.
    """
    from lesysbot.cli import artifacts, dashboard, doctor, search
    from lesysbot.setup.cli import register_subcommand as register_setup

    artifacts.register(subparsers)
    search.register(subparsers)
    doctor.register(subparsers)
    dashboard.register(subparsers)
    register_setup(subparsers)


def handles(command: str | None) -> bool:
    """True when :func:`dispatch` owns *command* (vs. the bot/status paths)."""
    return command in _HANDLERS


def dispatch(args: argparse.Namespace) -> int:
    """Run the handler for ``args.command``; returns its exit code."""
    import importlib

    module = importlib.import_module(_HANDLERS[args.command])
    return module.run(args)
