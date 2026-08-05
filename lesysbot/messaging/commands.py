"""Native platform slash commands, described once for every adapter.

Both remote adapters have always routed a plain `/tool args` message straight to
`Agent._handle_slash`, so calling a tool without the LLM already worked. What was
missing is **discoverability**: Telegram's `/` menu and Discord's command picker
only offer commands the bot has *registered with the platform*, so until it does,
you have to already know a tool's name to type it.

Registration is what this module feeds. It builds one list of specs from the tool
registry and both adapters render it in their own idiom — Telegram a flat
name+description menu, Discord a typed application command per tool — so the two
platforms can't drift on which tools are offered or how they're described.

Both platforms enforce near-identical limits on a command name (lowercase
`a-z0-9_`, 32 characters) and cap a bot at 100 commands, so those constraints
live here rather than in either adapter. Descriptions are clamped to Discord's
100 characters, the tighter of the two, so one spec is valid on both.

A tool whose name isn't a legal command name is **skipped rather than renamed**:
a renamed command would no longer match the tool name that `_handle_slash` (and
`/help`, and the docs) expect, and silently answering to a different name is
worse than not appearing in the menu. Skipped tools stay callable as text.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Lowercase letters, digits and underscore only — the intersection of Telegram's
# and Discord's command-name rules.
_VALID_NAME = re.compile(r"^[a-z0-9_]{1,32}$")

MAX_DESCRIPTION_LEN = 100  # Discord's cap; Telegram allows 256
MAX_COMMANDS = 100  # per bot, on both platforms


@dataclass(frozen=True)
class ParamSpec:
    name: str
    description: str
    json_type: str
    required: bool


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)


# The agent's own commands, handled by `_handle_slash` before any tool lookup.
# `/help` is deliberately first: it is the one command that explains the rest.
BUILTIN_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("help", "List every tool you can call"),
    CommandSpec("clear", "Forget the conversation history"),
    CommandSpec("history", "Show the conversation so far"),
)


def _clamp(text: str, limit: int = MAX_DESCRIPTION_LEN) -> str:
    """Fit *text* to *limit*, ellipsised. Never empty — both platforms reject
    a blank description, and a tool with no docstring is allowed."""
    text = " ".join((text or "").split()) or "Run this tool"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def tool_commands(registry: Any) -> list[CommandSpec]:
    """Specs for every tool that can actually be called right now.

    Disabled tools and tools gated off this OS are left out: the menu answers
    "what can I run", and offering a command whose only reply is "that's
    disabled" wastes one of the 100 slots to teach nothing.
    """
    specs: list[CommandSpec] = []
    skipped: list[str] = []
    for row in registry.tool_status():
        name = row["name"]
        if not row["enabled"] or not row["available"]:
            continue
        if not _VALID_NAME.match(name):
            skipped.append(name)
            continue
        meta = registry.get_tool_meta(name) or {}
        properties = meta.get("parameters", {}).get("properties", {})
        params = tuple(
            ParamSpec(
                name=param["name"],
                # `@tool` records no per-parameter text (CLITool does), so fall
                # back to the name — a description is mandatory on Discord.
                description=_clamp(
                    (properties.get(param["name"]) or {}).get("description")
                    or param["name"]
                ),
                json_type=(properties.get(param["name"]) or {}).get("type", "string"),
                required=param["required"],
            )
            for param in row["params"]
            if _VALID_NAME.match(param["name"])
        )
        specs.append(CommandSpec(name, _clamp(row["description"]), params))

    if skipped:
        logger.warning(
            "Not registering %d tool(s) as slash commands — names must be "
            "lowercase letters, digits or underscore (max 32): %s. They still "
            "work as typed messages.",
            len(skipped), ", ".join(sorted(skipped)),
        )
    return specs


def all_commands(registry: Any) -> list[CommandSpec]:
    """Built-ins plus tools, trimmed to what a bot is allowed to register."""
    specs = [*BUILTIN_COMMANDS, *tool_commands(registry)]
    if len(specs) > MAX_COMMANDS:
        dropped = len(specs) - MAX_COMMANDS
        logger.warning(
            "%d tools exceed the %d-command platform limit — %d will not appear "
            "in the command menu (still callable as typed messages).",
            len(specs), MAX_COMMANDS, dropped,
        )
        specs = specs[:MAX_COMMANDS]
    return specs


def to_slash_text(name: str, arguments: dict[str, Any]) -> str:
    """Render a native command invocation as the `/name key=value` text form.

    Native commands are a typed front door onto the text path, not a second
    dispatcher: rebuilding the message means confirmation gating, tracing, the
    out-of-band-push user stamp and the built-ins all keep working through the
    one code path in `Agent._handle_slash`. `registry.call()` coerces the values
    back to their declared types, so the round trip through text is lossless.

    ``None`` values are dropped — that is how an optional Discord option arrives
    when the user left it blank, and passing it on would override the tool's own
    default with nothing.
    """
    parts = [f"/{name}"]
    for key, value in arguments.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{key}={shlex.quote(str(value))}")
    return " ".join(parts)
