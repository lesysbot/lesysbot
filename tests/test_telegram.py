"""Tests for the Telegram adapter (lesysbot/messaging/telegram.py): the `/`
command menu it publishes, and the `@botname` suffix groups append to commands.
Network-free — no Application is ever built.
"""
from __future__ import annotations

from telegram.error import TelegramError

from lesysbot.core.config import TelegramConfig
from lesysbot.messaging.telegram import TelegramAdapter, _strip_bot_mention
from lesysbot.mcp import tool
from lesysbot.mcp.registry import ToolRegistry


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.commands: list[tuple[str, str]] | None = None
        self._fail = fail

    async def set_my_commands(self, commands) -> None:
        if self._fail:
            raise TelegramError("flood wait")
        self.commands = [(c.command, c.description) for c in commands]


class FakeApp:
    def __init__(self, fail: bool = False) -> None:
        self.bot = FakeBot(fail=fail)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    @tool(description="Check free disk space")
    def disk_usage(path: str) -> str:
        return path

    registry.register_callable(disk_usage)
    return registry


def _adapter(registry=None, fail: bool = False) -> TelegramAdapter:
    adapter = TelegramAdapter(TelegramConfig(token="t"), registry)
    adapter._app = FakeApp(fail=fail)  # type: ignore[assignment]
    return adapter


# ── the `/` command menu ───────────────────────────────────────────────────


async def test_tools_are_published_to_the_command_menu():
    adapter = _adapter(_registry())
    await adapter._register_commands()

    names = [name for name, _ in adapter._app.bot.commands]
    assert names[:3] == ["help", "clear", "history"]
    assert "disk_usage" in names
    assert dict(adapter._app.bot.commands)["disk_usage"] == "Check free disk space"


async def test_no_menu_is_published_without_a_registry():
    # Tools stay callable as typed text; there is just nothing to advertise.
    adapter = _adapter(None)
    await adapter._register_commands()
    assert adapter._app.bot.commands is None


async def test_a_failed_registration_does_not_take_the_bot_down(caplog):
    # Losing an autocomplete menu must not stop a service from starting.
    adapter = _adapter(_registry(), fail=True)
    with caplog.at_level("WARNING"):
        await adapter._register_commands()
    assert "Could not register the Telegram command menu" in caplog.text


async def test_disabled_tools_are_left_out_of_the_menu():
    registry = _registry()
    registry.disable("disk_usage")
    adapter = _adapter(registry)
    await adapter._register_commands()
    assert "disk_usage" not in [name for name, _ in adapter._app.bot.commands]


# ── group chats append @botname to commands ────────────────────────────────


def test_bot_mention_is_stripped_from_a_command():
    assert _strip_bot_mention("/disk_usage@my_bot /tmp", "my_bot") == "/disk_usage /tmp"


def test_bot_mention_is_stripped_from_a_bare_command():
    assert _strip_bot_mention("/help@my_bot", "my_bot") == "/help"


def test_another_bots_mention_is_left_alone():
    # Telegram routes it to that bot, not us; rewriting it would be wrong.
    assert _strip_bot_mention("/help@other_bot", "my_bot") == "/help@other_bot"


def test_plain_text_and_arguments_are_untouched():
    assert _strip_bot_mention("how much disk is free?", "my_bot") == (
        "how much disk is free?"
    )
    # An @ inside an argument is not a command suffix.
    assert _strip_bot_mention("/mail to=a@my_bot", "my_bot") == "/mail to=a@my_bot"


def test_unknown_username_is_a_no_op():
    assert _strip_bot_mention("/help@my_bot", None) == "/help@my_bot"
