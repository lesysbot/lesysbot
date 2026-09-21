"""Discord adapter — LeSysBot as a Discord bot you DM or @-mention.

One bot token, one persistent gateway websocket (no public URL, no polling).
Two Discord-specific facts shape everything below:

* **The Message Content intent is privileged.** Without it enabled in the
  developer portal the gateway still delivers every message, but with an empty
  ``content`` — the bot looks deaf while logging nothing. ``start()`` turns that
  into one actionable line, and a first empty message logs a warning naming the
  toggle, because for a background service that log is the user's only clue.
* **A bot sees every channel it was invited to.** Answering all of them would
  make LeSysBot shout over a server, so guild messages are handled only when the
  bot is @-mentioned. DMs need no mention.

Tools are reachable two ways. A typed `/disk_usage path=/` message goes to
`Agent._handle_slash` like it does everywhere. On top of that, every tool is
registered as a **native application command**, so it shows up in Discord's `/`
picker with typed, described fields — see `_build_commands`, which routes those
back through the same text path rather than dispatching separately.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any, Optional

import discord
from discord import app_commands

from lesysbot.core.config import DiscordConfig
from lesysbot.messaging.base import (
    MessageHandler as BotHandler,
    MessagingAdapter,
    split_message,
)
from lesysbot.messaging.commands import CommandSpec, all_commands, to_slash_text

logger = logging.getLogger(__name__)

_MAX_MSG_LEN = 1900  # Discord hard limit is 2000; leave headroom
_CONFIRM_TIMEOUT = 300.0  # seconds a confirmation prompt stays answerable

# JSON schema type → the Python annotation Discord derives an option type from.
# array/object have no sane single-field form, so they arrive as text and the
# registry's coercion leaves them alone.
_OPTION_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}

# <@123> and the legacy nickname form <@!123>, so a mention-prefixed message
# reaches the agent as the question the user actually typed.
_MENTION = re.compile(r"<@!?(\d+)>")


def _drop_voice_warnings(record: logging.LogRecord) -> bool:
    """Filter out discord.py's "voice will NOT be supported" startup warnings."""
    return "voice will NOT be supported" not in record.getMessage()


# discord.py warns that PyNaCl/davey are missing so voice won't work — twice,
# while the Client is being constructed. LeSysBot is text-only, so that is noise
# about a feature nobody asked for, and it would greet every service start.
# Attached at import: this module is only imported for the discord provider, and
# the warnings fire before any of our own code gets a chance to run.
logging.getLogger("discord.client").addFilter(_drop_voice_warnings)


class _ConfirmView(discord.ui.View):
    """✅/❌ buttons backing :meth:`DiscordAdapter.confirm`.

    ``View.wait()`` already gives us "resolved or timed out", so there is no
    pending-callback bookkeeping here — unlike Telegram, where the answer
    arrives as a separate update that has to be matched back up by id.
    """

    def __init__(self, user_id: int, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self._user_id = user_id
        self.result: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # In a guild channel everyone can see (and click) these buttons. Only
        # the user whose tool call this is may answer for it.
        if interaction.user.id != self._user_id:
            await interaction.response.send_message(
                "This confirmation isn't yours to answer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Yes", emoji="✅", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, True)

    @discord.ui.button(label="No", emoji="❌", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._finish(interaction, False)

    async def _finish(self, interaction: discord.Interaction, choice: bool) -> None:
        self.result = choice
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        status = "✅ Confirmed" if choice else "❌ Cancelled"
        original = interaction.message.content if interaction.message else ""
        try:
            await interaction.response.edit_message(
                content=f"{original}\n\n{status}", view=self
            )
        except discord.HTTPException:
            # The prompt may have been deleted, or the interaction already
            # acknowledged. The answer is recorded either way — never let a
            # cosmetic edit failure turn into a refused tool call.
            logger.debug("Could not update confirmation message", exc_info=True)
        self.stop()


class DiscordAdapter(MessagingAdapter):
    def __init__(self, config: DiscordConfig, registry: Any = None) -> None:
        self._config = config
        # The tool registry, when the caller has one: it is what the application
        # commands are built from. Optional so the adapter still works standalone
        # (tools stay callable as typed text either way).
        self._registry = registry
        # message_content is privileged and must also be ticked in the portal;
        # everything else the adapter needs is in the default set.
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)
        # Resolved send targets (user DM channels / guild channels) by id, so a
        # repeated push doesn't re-fetch. Populated lazily by _destination().
        self._targets: dict[int, Any] = {}
        # Where each user last spoke, so a confirmation prompt appears in the
        # channel they asked in rather than surprising them in a DM.
        self._last_channel: dict[int, Any] = {}
        self._warned_empty_content = False

    # ------------------------------------------------------------------
    # Confirmation via message buttons
    # ------------------------------------------------------------------

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        lines = [f"⚠️ **{prompt}**", f"Tool: `{tool_name}`"]
        if args:
            args_lines = "\n".join(f"  • {k}: `{v}`" for k, v in args.items())
            lines.append(f"Args:\n{args_lines}")

        try:
            dest = await self._reply_target(user_id)
        except Exception as exc:
            # No way to ask means no consent — refuse rather than run a
            # confirm-gated tool unattended.
            logger.warning("Cannot reach %s to confirm %s: %s", user_id, tool_name, exc)
            return False

        view = _ConfirmView(int(user_id), _CONFIRM_TIMEOUT)
        await dest.send("\n".join(lines), view=view)

        if await view.wait():  # True = timed out without an answer
            logger.warning("Confirmation timed out for %s", tool_name)
            return False
        return bool(view.result)

    # ------------------------------------------------------------------
    # Adapter lifecycle
    # ------------------------------------------------------------------

    async def start(self, handler: BotHandler) -> None:
        client = self._client
        allowed = set(self._config.allowed_user_ids)
        if not allowed:
            logger.warning(
                "discord.allowed_user_ids is empty — ANY Discord user who can "
                "reach this bot (anyone sharing a server with it) can run its "
                "tools. Add your numeric user id to allowed_user_ids in "
                "config.yaml to lock it down."
            )

        def _authorized(user_id: int) -> bool:
            return not allowed or user_id in allowed

        @client.event
        async def setup_hook() -> None:
            # Runs once after login, before the gateway connects — the point at
            # which the application id exists and commands can be synced. Doing
            # it in on_ready instead would re-sync on every reconnect.
            self._build_commands(handler, _authorized)
            await self._sync_commands()

        @client.event
        async def on_ready() -> None:
            logger.info("Discord bot connected as %s", client.user)
            self.ready.set()  # gateway is up — the startup notice may send now

        @client.event
        async def on_message(message: discord.Message) -> None:
            # Never answer ourselves (or another bot) — that is how loops start.
            if message.author.bot:
                return

            is_dm = message.guild is None
            mentions_us = client.user in message.mentions
            # In a server the bot is one member among many; replying to every
            # message it can see would be unusable. A mention is the opt-in.
            if not is_dm and not mentions_us:
                return

            text = _MENTION.sub("", message.content).strip()
            if not text:
                if not message.content and not self._warned_empty_content:
                    self._warned_empty_content = True
                    logger.warning(
                        "Received a Discord message with empty content — enable "
                        "the MESSAGE CONTENT INTENT for this bot at "
                        "https://discord.com/developers/applications (Bot → "
                        "Privileged Gateway Intents) and restart."
                    )
                return

            user_id = str(message.author.id)
            if allowed and message.author.id not in allowed:
                await message.channel.send("Unauthorized.")
                return

            # Remember where to put a confirmation prompt for this user.
            self._last_channel[message.author.id] = message.channel

            async with message.channel.typing():
                reply = await handler(user_id, text)
            for chunk in split_message(reply, _MAX_MSG_LEN):
                await message.channel.send(chunk)

        logger.info("Discord bot starting (gateway)...")
        try:
            # start() connects and then blocks until the client is closed; the
            # ready event above is what the startup notice waits on.
            await client.start(self._config.token)
        # Both failures below are configuration mistakes, not crashes. Exit on
        # one actionable line: a traceback here would bury the fix, and for a
        # background service the log is the only place the user ever sees it.
        except discord.PrivilegedIntentsRequired:
            logger.error(
                "Discord refused the connection: the MESSAGE CONTENT INTENT is "
                "not enabled for this bot. Turn it on at "
                "https://discord.com/developers/applications → your app → Bot → "
                "Privileged Gateway Intents, then restart."
            )
            raise SystemExit(1) from None
        except discord.LoginFailure:
            logger.error(
                "Discord rejected the bot token. Copy it again from "
                "https://discord.com/developers/applications → your app → Bot → "
                "Reset Token, and set messaging.discord.token in config.yaml."
            )
            raise SystemExit(1) from None
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            if not client.is_closed():
                await client.close()

    async def send(self, user_id: str, text: str) -> None:
        if self._client.is_closed():
            return
        dest = await self._reply_target(user_id)
        for chunk in split_message(text, _MAX_MSG_LEN):
            await dest.send(chunk)

    # ------------------------------------------------------------------
    # Native application commands
    # ------------------------------------------------------------------

    def _build_commands(self, handler: BotHandler, authorized) -> None:
        """Add one typed application command per tool, plus the built-ins.

        These are a **front door onto the text path**, not a second dispatcher:
        each callback rebuilds the `/name key=value` message and hands it to the
        same `handler` a typed message goes through, so confirmation gating,
        tracing and the out-of-band-push user stamp all keep working from one
        place. `registry.call()` coerces the values back to their declared types,
        so nothing is lost in the round trip.
        """
        if self._registry is None:
            return
        for spec in all_commands(self._registry):
            try:
                self._tree.add_command(self._make_command(spec, handler, authorized))
            except Exception:
                # One malformed tool must not cost the whole command menu.
                logger.warning(
                    "Could not build a Discord command for /%s", spec.name,
                    exc_info=True,
                )

    def _make_command(
        self, spec: CommandSpec, handler: BotHandler, authorized
    ) -> app_commands.Command:
        async def callback(interaction: discord.Interaction, **kwargs: Any) -> None:
            await self._invoke(interaction, spec, kwargs, handler, authorized)

        # discord.py derives an option per callback parameter, from the
        # signature and annotations — so a command whose parameters are only
        # known at runtime needs both synthesised. Optional params get a None
        # default, which `to_slash_text` drops so the tool's own default applies.
        parameters = [
            inspect.Parameter(
                "interaction",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=discord.Interaction,
            )
        ]
        annotations: dict[str, Any] = {"interaction": discord.Interaction}
        for param in spec.params:
            py_type = _OPTION_TYPES.get(param.json_type, str)
            annotation = py_type if param.required else Optional[py_type]
            annotations[param.name] = annotation
            parameters.append(
                inspect.Parameter(
                    param.name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                    default=inspect.Parameter.empty if param.required else None,
                )
            )
        callback.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
        callback.__annotations__ = annotations

        command = app_commands.Command(
            name=spec.name, description=spec.description, callback=callback
        )
        if spec.params:
            # Applied to the built command (the public `describe` API handles
            # that case) rather than by setting discord.py's private attribute.
            app_commands.describe(
                **{param.name: param.description for param in spec.params}
            )(command)
        return command

    async def _invoke(
        self,
        interaction: discord.Interaction,
        spec: CommandSpec,
        kwargs: dict[str, Any],
        handler: BotHandler,
        authorized,
    ) -> None:
        user = interaction.user
        if not authorized(user.id):
            await interaction.response.send_message("Unauthorized.", ephemeral=True)
            return

        # A tool can easily outrun Discord's 3-second window for the first
        # interaction response, and a missed one shows the user "the application
        # did not respond". Defer immediately, then follow up with the result.
        await interaction.response.defer(thinking=True)

        # So a confirmation prompt lands where the command was run.
        if interaction.channel is not None:
            self._last_channel[user.id] = interaction.channel

        text = to_slash_text(spec.name, kwargs)
        try:
            reply = await handler(str(user.id), text)
        except Exception:
            logger.exception("Command /%s failed", spec.name)
            reply = f"`/{spec.name}` failed — check the LeSysBot log."

        chunks = split_message(reply, _MAX_MSG_LEN) or ["(no output)"]
        for chunk in chunks:
            await interaction.followup.send(chunk)

    async def _sync_commands(self) -> None:
        """Publish the command set to Discord.

        Best-effort: a failure here costs the command picker, not the bot, and a
        service that refused to start over a cosmetic API call would be worse.

        Synced once at startup, so tools added by hot reload (or toggled with
        `lesysbot enable/disable`) reach the picker on the next restart —
        they are callable as typed messages immediately either way. Re-syncing on
        every tools-dir change would burn Discord's command-update rate limit.
        """
        try:
            synced = await self._tree.sync()
            logger.info("Registered %d Discord application commands", len(synced))
        except discord.HTTPException as exc:
            logger.warning("Could not register Discord commands: %s", exc)

    async def _reply_target(self, user_id: str):
        """Where to address *user_id*: the channel they last spoke in, else a DM.

        A tool's out-of-band push (`notify_later`) and a confirmation prompt are
        both continuations of a conversation, so they belong where that
        conversation is happening — surprising someone in their DMs because they
        asked in a channel is worse than either. The startup notice hits the
        fallback instead: at boot nobody has spoken yet, and a `notify` entry may
        name a channel outright.
        """
        target = self._last_channel.get(int(user_id))
        return target if target is not None else await self._destination(user_id)

    async def _destination(self, target_id: str):
        """Resolve a Discord id to something sendable.

        `notify`/`notify_later` hand us a bare snowflake that may be either a
        user (open a DM) or a channel, and nothing in the id says which. Guild
        channels the bot can see are already cached by the gateway, so try that
        first, then a DM — a user id is what `Agent` stamps for out-of-band
        pushes — and only then pay for an uncached channel fetch.
        """
        try:
            snowflake = int(target_id)
        except (TypeError, ValueError):
            raise ValueError(
                f"{target_id!r} is not a Discord id — ids are numeric snowflakes. "
                "Enable Developer Mode (Settings → Advanced), then right-click a "
                "user or channel → Copy ID."
            ) from None

        cached = self._targets.get(snowflake)
        if cached is not None:
            return cached

        dest = self._client.get_channel(snowflake)
        if dest is None:
            try:
                user = await self._client.fetch_user(snowflake)
                dest = user.dm_channel or await user.create_dm()
            except discord.NotFound:
                dest = await self._client.fetch_channel(snowflake)
        self._targets[snowflake] = dest
        return dest
