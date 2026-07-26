"""Tests for the Discord adapter (lesysbot/messaging/discord.py) and the shared
message splitter. Network-free: the gateway is never contacted — `Client.start`
is stubbed out so the registered `on_message` handler can be driven directly.
"""
from __future__ import annotations

import contextlib

import discord
import pytest

from lesysbot.core.config import DiscordConfig
from lesysbot.messaging.base import split_message
from lesysbot.messaging.discord import _MAX_MSG_LEN, DiscordAdapter


# ── fakes ──────────────────────────────────────────────────────────────────


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.views: list[object] = []

    async def send(self, content: str, view: object = None) -> None:
        self.sent.append(content)
        if view is not None:
            self.views.append(view)

    @contextlib.asynccontextmanager
    async def typing(self):
        yield


class FakeAuthor:
    def __init__(self, user_id: int, bot: bool = False) -> None:
        self.id = user_id
        self.bot = bot


class FakeMessage:
    def __init__(self, content, author, channel, guild=None, mentions=()) -> None:
        self.content = content
        self.author = author
        self.channel = channel
        self.guild = guild
        self.mentions = list(mentions)


class FakeClient:
    """Enough of discord.Client for the adapter's own logic."""

    def __init__(self, me: object = None) -> None:
        self.user = me
        self.channels: dict[int, FakeChannel] = {}
        self.users: dict[int, object] = {}
        self.fetched: list[int] = []
        self.closed = False

    def get_channel(self, snowflake: int):
        return self.channels.get(snowflake)

    async def fetch_user(self, snowflake: int):
        self.fetched.append(snowflake)
        user = self.users.get(snowflake)
        if user is None:
            raise discord.NotFound(_FakeResponse(), "unknown user")
        return user

    async def fetch_channel(self, snowflake: int):
        self.fetched.append(snowflake)
        channel = self.channels.get(snowflake)
        if channel is None:
            raise discord.NotFound(_FakeResponse(), "unknown channel")
        return channel

    def is_closed(self) -> bool:
        return self.closed


class _FakeResponse:
    """Minimal aiohttp-response stand-in for constructing discord.NotFound."""

    status = 404
    reason = "Not Found"


class FakeUser:
    def __init__(self, dm: FakeChannel | None = None) -> None:
        self.dm_channel = dm
        self.created: FakeChannel | None = None

    async def create_dm(self) -> FakeChannel:
        self.created = FakeChannel()
        return self.created


def make_adapter(allowed: list[int] | None = None, me: object = None) -> DiscordAdapter:
    adapter = DiscordAdapter(DiscordConfig(token="t", allowed_user_ids=allowed or []))
    adapter._client = FakeClient(me=me)  # type: ignore[assignment]
    return adapter


async def start_handler(adapter: DiscordAdapter, handler):
    """Run `start()` with the gateway stubbed out, returning `on_message`."""
    client = adapter._client

    async def fake_start(_token):
        return None

    async def fake_close():
        client.closed = True

    client.start = fake_start          # type: ignore[attr-defined]
    client.close = fake_close          # type: ignore[attr-defined]
    client.event = lambda coro: setattr(client, coro.__name__, coro)  # type: ignore[attr-defined]
    await adapter.start(handler)
    # In production `start()` blocks for the life of the bot, so messages and
    # sends happen while the client is still open. Here it returns immediately
    # and the `finally` closes it — undo that, or every send would short-circuit.
    client.closed = False
    return client.on_message           # type: ignore[attr-defined]


# ── split_message (shared with the Telegram adapter) ───────────────────────


def test_split_returns_short_text_unchanged():
    assert split_message("hello", 100) == ["hello"]


def test_split_chunks_long_text_to_the_limit():
    chunks = split_message("x" * 250, 100)
    assert [len(c) for c in chunks] == [100, 100, 50]
    assert "".join(chunks) == "x" * 250


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_split_drops_empty_text(text):
    # Both APIs reject an empty message body, so there is nothing to send.
    assert split_message(text, 100) == []


def test_discord_limit_leaves_headroom_under_2000():
    assert _MAX_MSG_LEN < 2000


# ── message routing ────────────────────────────────────────────────────────


async def test_dm_reaches_the_handler_and_replies():
    me = FakeAuthor(999, bot=True)
    adapter = make_adapter(me=me)
    seen: list[tuple[str, str]] = []

    async def handler(user_id, text, **kwargs):
        seen.append((user_id, text))
        return "pong"

    on_message = await start_handler(adapter, handler)
    channel = FakeChannel()
    await on_message(FakeMessage("ping", FakeAuthor(7), channel))

    assert seen == [("7", "ping")]
    assert channel.sent == ["pong"]


async def test_guild_message_ignored_unless_the_bot_is_mentioned():
    me = FakeAuthor(999, bot=True)
    adapter = make_adapter(me=me)
    calls: list[str] = []

    async def handler(user_id, text, **kwargs):
        calls.append(text)
        return "ok"

    on_message = await start_handler(adapter, handler)
    channel = FakeChannel()
    guild = object()

    # Chatter in a channel the bot happens to be in: not for us.
    await on_message(FakeMessage("hey everyone", FakeAuthor(7), channel, guild=guild))
    assert calls == []
    assert channel.sent == []

    # Mentioned: handled, and the mention is stripped from the question.
    await on_message(
        FakeMessage("<@999> disk usage?", FakeAuthor(7), channel, guild=guild, mentions=[me])
    )
    assert calls == ["disk usage?"]
    assert channel.sent == ["ok"]


async def test_bot_messages_are_ignored():
    adapter = make_adapter(me=FakeAuthor(999, bot=True))
    calls: list[str] = []

    async def handler(user_id, text, **kwargs):
        calls.append(text)
        return "ok"

    on_message = await start_handler(adapter, handler)
    await on_message(FakeMessage("ping", FakeAuthor(1, bot=True), FakeChannel()))
    assert calls == []


async def test_allow_list_rejects_other_users():
    adapter = make_adapter(allowed=[7], me=FakeAuthor(999, bot=True))
    calls: list[str] = []

    async def handler(user_id, text, **kwargs):
        calls.append(text)
        return "ok"

    on_message = await start_handler(adapter, handler)

    stranger = FakeChannel()
    await on_message(FakeMessage("ping", FakeAuthor(8), stranger))
    assert calls == []
    assert stranger.sent == ["Unauthorized."]

    mine = FakeChannel()
    await on_message(FakeMessage("ping", FakeAuthor(7), mine))
    assert calls == ["ping"]
    assert mine.sent == ["ok"]


async def test_empty_content_warns_about_the_message_content_intent(caplog):
    adapter = make_adapter(me=FakeAuthor(999, bot=True))

    async def handler(user_id, text, **kwargs):  # pragma: no cover - never reached
        return "ok"

    on_message = await start_handler(adapter, handler)
    with caplog.at_level("WARNING"):
        await on_message(FakeMessage("", FakeAuthor(7), FakeChannel()))
    assert "MESSAGE CONTENT INTENT" in caplog.text


async def test_long_reply_is_sent_as_several_messages():
    adapter = make_adapter(me=FakeAuthor(999, bot=True))

    async def handler(user_id, text, **kwargs):
        return "y" * (_MAX_MSG_LEN + 10)

    on_message = await start_handler(adapter, handler)
    channel = FakeChannel()
    await on_message(FakeMessage("go", FakeAuthor(7), channel))
    assert [len(c) for c in channel.sent] == [_MAX_MSG_LEN, 10]


# ── destination resolution (startup notice / notify_later) ─────────────────


async def test_destination_prefers_a_cached_channel():
    adapter = make_adapter()
    channel = FakeChannel()
    adapter._client.channels[123] = channel

    assert await adapter._destination("123") is channel
    assert adapter._client.fetched == []  # no HTTP call needed


async def test_destination_opens_a_dm_for_a_user_id():
    adapter = make_adapter()
    user = FakeUser()
    adapter._client.users[55] = user

    dest = await adapter._destination("55")
    assert dest is user.created

    # Second call is served from the cache, not re-fetched.
    assert await adapter._destination("55") is user.created
    assert adapter._client.fetched == [55]


async def test_destination_falls_back_to_a_channel_fetch():
    adapter = make_adapter()
    channel = FakeChannel()
    # Known as a channel but not as a user, and not in the gateway cache.
    adapter._client.channels[77] = channel
    adapter._client.get_channel = lambda _s: None  # type: ignore[assignment]

    assert await adapter._destination("77") is channel


async def test_destination_rejects_a_non_numeric_id():
    adapter = make_adapter()
    with pytest.raises(ValueError, match="numeric snowflakes"):
        await adapter._destination("#general")


async def test_send_follows_the_channel_the_user_last_spoke_in():
    # An out-of-band push (notify_later) continues the conversation, so it lands
    # in the channel the user asked in rather than in their DMs.
    adapter = make_adapter(me=FakeAuthor(999, bot=True))

    async def handler(user_id, text, **kwargs):
        return "ok"

    on_message = await start_handler(adapter, handler)
    channel = FakeChannel()
    guild = object()
    me = adapter._client.user
    await on_message(
        FakeMessage("<@999> go", FakeAuthor(7), channel, guild=guild, mentions=[me])
    )

    await adapter.send("7", "powering off now")
    assert channel.sent == ["ok", "powering off now"]
    assert adapter._client.fetched == []  # no DM opened


async def test_send_chunks_and_short_circuits_when_closed():
    adapter = make_adapter()
    user = FakeUser()
    adapter._client.users[55] = user

    await adapter.send("55", "hello")
    assert user.created.sent == ["hello"]

    adapter._client.closed = True
    await adapter.send("55", "dropped")
    assert user.created.sent == ["hello"]


# ── confirmation ───────────────────────────────────────────────────────────


async def test_confirm_prompts_in_the_channel_the_user_asked_in():
    adapter = make_adapter(me=FakeAuthor(999, bot=True))

    async def handler(user_id, text, **kwargs):
        return "ok"

    on_message = await start_handler(adapter, handler)
    channel = FakeChannel()
    await on_message(FakeMessage("ping", FakeAuthor(7), channel))

    # Answer the buttons as soon as the prompt lands, so wait() returns.
    real_send = channel.send

    async def send_and_answer(content, view=None):
        await real_send(content, view=view)
        if view is not None:
            view.result = True
            view.stop()

    channel.send = send_and_answer  # type: ignore[assignment]

    assert await adapter.confirm("7", "power_off", "Really?", {"delay": 1}) is True
    prompt = channel.sent[-1]
    assert "Really?" in prompt and "power_off" in prompt and "delay" in prompt


async def test_confirm_refuses_when_the_user_is_unreachable():
    # No cached channel and no such user: nothing to ask, so nothing runs.
    adapter = make_adapter()
    assert await adapter.confirm("404", "power_off", "Really?", {}) is False


# ── native application commands ────────────────────────────────────────────


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False
        self.messages: list[tuple[str, bool]] = []

    async def defer(self, thinking: bool = False) -> None:
        self.deferred = True

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append((content, ephemeral))


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class FakeInteraction:
    def __init__(self, user_id: int, channel=None) -> None:
        self.user = FakeAuthor(user_id)
        self.channel = channel
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def _tool_registry():
    from lesysbot.mcp import tool
    from lesysbot.mcp.registry import ToolRegistry

    reg = ToolRegistry()

    @tool(description="Check free disk space")
    def disk_usage(path: str, depth: int = 1) -> str:
        return path

    reg.register_callable(disk_usage)
    return reg


def _built(adapter, handler, authorized=lambda _uid: True):
    adapter._build_commands(handler, authorized)
    return {c.name: c for c in adapter._tree.get_commands()}


async def test_tools_are_registered_as_typed_application_commands():
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def handler(user_id, text, **kwargs):
        return "ok"

    built = _built(adapter, handler)
    assert {"help", "clear", "history", "disk_usage"} <= set(built)

    options = built["disk_usage"].to_dict(adapter._tree)["options"]
    assert [(o["name"], o["type"], o["required"]) for o in options] == [
        ("path", 3, True),      # 3 = string
        ("depth", 4, False),    # 4 = integer
    ]


async def test_no_commands_are_built_without_a_registry():
    # The adapter still works standalone; tools stay callable as typed text.
    adapter = make_adapter()
    assert _built(adapter, lambda *a, **k: None) == {}


async def test_invoking_a_command_routes_through_the_text_slash_path():
    adapter = make_adapter()
    adapter._registry = _tool_registry()
    seen: list[tuple[str, str]] = []

    async def handler(user_id, text, **kwargs):
        seen.append((user_id, text))
        return "143 GB free"

    built = _built(adapter, handler)
    interaction = FakeInteraction(7, channel=FakeChannel())
    await built["disk_usage"].callback(interaction, path="/", depth=None)

    # Rebuilt as the same message a user could have typed — one dispatch path.
    assert seen == [("7", "/disk_usage path=/")]
    assert interaction.response.deferred  # tools can outrun Discord's 3 s window
    assert interaction.followup.sent == ["143 GB free"]


async def test_invoking_a_command_remembers_the_channel_for_confirmations():
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def handler(user_id, text, **kwargs):
        return "ok"

    built = _built(adapter, handler)
    channel = FakeChannel()
    await built["disk_usage"].callback(FakeInteraction(7, channel=channel), path="/")
    assert adapter._last_channel[7] is channel


async def test_unauthorized_command_is_refused_privately():
    adapter = make_adapter()
    adapter._registry = _tool_registry()
    calls: list[str] = []

    async def handler(user_id, text, **kwargs):
        calls.append(text)
        return "ok"

    built = _built(adapter, handler, authorized=lambda uid: uid == 7)
    interaction = FakeInteraction(8, channel=FakeChannel())
    await built["disk_usage"].callback(interaction, path="/")

    assert calls == []
    assert interaction.response.messages == [("Unauthorized.", True)]
    assert interaction.followup.sent == []


async def test_command_long_output_is_chunked_into_followups():
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def handler(user_id, text, **kwargs):
        return "z" * (_MAX_MSG_LEN + 5)

    built = _built(adapter, handler)
    interaction = FakeInteraction(7, channel=FakeChannel())
    await built["disk_usage"].callback(interaction, path="/")
    assert [len(c) for c in interaction.followup.sent] == [_MAX_MSG_LEN, 5]


async def test_command_with_empty_output_still_answers():
    # A deferred interaction with no followup shows "the application did not
    # respond", which is worse than saying nothing happened.
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def handler(user_id, text, **kwargs):
        return "   "

    built = _built(adapter, handler)
    interaction = FakeInteraction(7, channel=FakeChannel())
    await built["disk_usage"].callback(interaction, path="/")
    assert interaction.followup.sent == ["(no output)"]


async def test_command_failure_is_reported_not_swallowed():
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def handler(user_id, text, **kwargs):
        raise RuntimeError("boom")

    built = _built(adapter, handler)
    interaction = FakeInteraction(7, channel=FakeChannel())
    await built["disk_usage"].callback(interaction, path="/")
    assert "failed" in interaction.followup.sent[0]


async def test_start_wires_setup_hook_to_build_and_sync_commands():
    # discord.py awaits Client.setup_hook() once at the end of login(), which is
    # the first point an application id exists and commands can be synced.
    adapter = make_adapter()
    adapter._registry = _tool_registry()
    synced: list[int] = []

    async def fake_sync():
        synced.append(len(adapter._tree.get_commands()))
        return adapter._tree.get_commands()

    adapter._tree.sync = fake_sync  # type: ignore[assignment]

    async def handler(user_id, text, **kwargs):
        return "ok"

    await start_handler(adapter, handler)
    setup_hook = adapter._client.setup_hook  # registered by start()
    assert adapter._tree.get_commands() == []  # nothing built until login
    await setup_hook()

    assert "disk_usage" in {c.name for c in adapter._tree.get_commands()}
    assert synced == [len(adapter._tree.get_commands())]


async def test_a_failed_sync_does_not_take_the_bot_down(caplog):
    adapter = make_adapter()
    adapter._registry = _tool_registry()

    async def fake_sync():
        raise discord.HTTPException(_FakeResponse(), "rate limited")

    adapter._tree.sync = fake_sync  # type: ignore[assignment]
    with caplog.at_level("WARNING"):
        await adapter._sync_commands()
    assert "Could not register Discord commands" in caplog.text
