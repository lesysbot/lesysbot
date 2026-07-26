from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from lesysbot.core.config import TelegramConfig
from lesysbot.messaging.base import (
    MessageHandler as BotHandler,
    MessagingAdapter,
    split_message,
)
from lesysbot.messaging.commands import all_commands

logger = logging.getLogger(__name__)

_MAX_MSG_LEN = 4000  # Telegram hard limit is 4096; leave headroom


class TelegramAdapter(MessagingAdapter):
    def __init__(self, config: TelegramConfig, registry: Any = None) -> None:
        self._config = config
        # The tool registry, when the caller has one: it is what the platform's
        # slash-command menu is built from. Optional so the adapter still works
        # standalone (tools stay callable as typed text either way).
        self._registry = registry
        self._app: Application | None = None
        # Pending confirmation callbacks keyed by callback_id
        self._pending: dict[str, asyncio.Event] = {}
        self._confirmed: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Confirmation via inline keyboard buttons
    # ------------------------------------------------------------------

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        if not self._app:
            return True

        callback_id = uuid.uuid4().hex[:8]
        event = asyncio.Event()
        self._pending[callback_id] = event

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"confirm:{callback_id}:yes"),
                InlineKeyboardButton("❌ No", callback_data=f"confirm:{callback_id}:no"),
            ]
        ])

        lines = [f"⚠️ *{prompt}*", f"Tool: `{tool_name}`"]
        if args:
            args_lines = "\n".join(f"  • {k}: `{v}`" for k, v in args.items())
            lines.append(f"Args:\n{args_lines}")

        text = "\n".join(lines)
        try:
            await self._app.bot.send_message(
                chat_id=int(user_id),
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        except BadRequest:
            # Tool args with Markdown-hostile characters (lone "_", "*", …) must
            # not kill the prompt — the user would never get asked and the
            # confirmation would time out. Resend plain.
            await self._app.bot.send_message(
                chat_id=int(user_id), text=text, reply_markup=keyboard
            )

        try:
            await asyncio.wait_for(event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            self._pending.pop(callback_id, None)
            logger.warning("Confirmation timed out for %s/%s", tool_name, callback_id)
            return False
        finally:
            self._pending.pop(callback_id, None)

        return self._confirmed.pop(callback_id, False)

    # ------------------------------------------------------------------
    # Adapter lifecycle
    # ------------------------------------------------------------------

    async def start(self, handler: BotHandler) -> None:
        # concurrent_updates(True) is REQUIRED for the confirmation flow: confirm()
        # blocks on_message awaiting a button press, and PTB processes updates
        # sequentially by default — so the callback-query update carrying that press
        # would queue *behind* the very handler waiting on it, deadlocking until the
        # 120s timeout fires (Telegram then rejects the now-stale callback as "too old").
        self._app = (
            Application.builder()
            .token(self._config.token)
            .concurrent_updates(True)
            .build()
        )
        allowed = set(self._config.allowed_user_ids)
        if not allowed:
            logger.warning(
                "telegram.allowed_user_ids is empty — ANY Telegram user who finds "
                "this bot can run its tools. Add your numeric user id to "
                "allowed_user_ids in config.yaml to lock it down."
            )

        def _authorized(user_id: str) -> bool:
            return not allowed or int(user_id) in allowed

        async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.effective_user:
                return
            user_id = str(update.effective_user.id)
            if not _authorized(user_id):
                await update.message.reply_text("Unauthorized.")
                return

            # In a group Telegram appends the bot's username to a command
            # (`/disk_usage@my_bot`), which would reach the agent as an unknown
            # command. Strip it so group chats behave like DMs.
            text = _strip_bot_mention(update.message.text or "", ctx.bot.username)

            # /start is a Telegram convention — give a friendly greeting
            if text.strip() == "/start":
                await update.message.reply_text(
                    "👋 Hi\\! I'm *LeSysBot*\\.\n\n"
                    "Send me a message to chat with the AI, or use `/help` to "
                    "see available tool commands \\(no LLM needed\\)\\.",
                    parse_mode="MarkdownV2",
                )
                return

            reply = await handler(user_id, text)
            for chunk in split_message(reply, _MAX_MSG_LEN):
                await _reply_safe(update.message, chunk)

        async def on_callback_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            query = update.callback_query
            if not query:
                return
            try:
                await query.answer()
            except BadRequest as exc:
                # Stale tap (e.g. an old prompt tapped after Telegram expired the
                # query): nothing to confirm anymore — drop it without a traceback.
                logger.debug("Ignoring stale callback query: %s", exc)
                return
            data = query.data or ""
            if not data.startswith("confirm:"):
                return
            parts = data.split(":", 2)
            if len(parts) != 3:
                return
            _, callback_id, choice = parts
            if callback_id in self._pending:
                self._confirmed[callback_id] = choice == "yes"
                self._pending[callback_id].set()
            status = "✅ Confirmed" if choice == "yes" else "❌ Cancelled"
            if query.message:
                try:
                    # query.message.text is rendered plain text — re-parsing it as
                    # Markdown fails on e.g. the "_" in `power_off` (BadRequest),
                    # which would silently drop this ack and leave the buttons up.
                    # Keep the original entities instead: the old text is an
                    # unchanged prefix, so their offsets stay valid.
                    await query.edit_message_text(
                        f"{query.message.text}\n\n{status}",
                        entities=query.message.entities,
                    )
                except Exception:
                    pass  # message may have been deleted

        async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            # One place for unhandled errors so PTB stops logging
            # "No error handlers are registered" with a bare traceback.
            logger.warning("Telegram update error: %s", ctx.error)

        # Route ALL text messages (including /commands) to on_message so
        # the agent's slash-command handler can process them without LLM.
        self._app.add_handler(MessageHandler(filters.TEXT, on_message))
        self._app.add_handler(CallbackQueryHandler(on_callback_query))
        self._app.add_error_handler(on_error)

        logger.info("Telegram bot starting (polling)...")
        await self._app.initialize()
        await self._register_commands()
        await self._app.start()
        await self._app.updater.start_polling()
        self.ready.set()  # bot is connected — the startup notice may send now

        # python-telegram-bot v20+ removed Updater.idle(); keep the coroutine
        # alive until cancelled (e.g. Ctrl-C), then shut down gracefully.
        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, user_id: str, text: str) -> None:
        if self._app:
            for chunk in split_message(text, _MAX_MSG_LEN):
                await self._app.bot.send_message(chat_id=int(user_id), text=chunk)

    async def _register_commands(self) -> None:
        """Publish the tool list to Telegram's `/` menu.

        Typing `/disk_usage /` always worked; this is what makes it *findable* —
        Telegram only shows commands the bot has registered. Telegram has no
        typed parameters, so a command is just a name and a description and the
        arguments stay free text, parsed by `Agent._handle_slash` as before.

        Best-effort: a failure here costs an autocomplete menu, not the bot, and
        a service that refused to start over a cosmetic API call would be worse.
        """
        if not self._app or self._registry is None:
            return
        specs = all_commands(self._registry)
        try:
            await self._app.bot.set_my_commands(
                [BotCommand(spec.name, spec.description) for spec in specs]
            )
            logger.info("Registered %d Telegram commands", len(specs))
        except TelegramError as exc:
            logger.warning("Could not register the Telegram command menu: %s", exc)


def _strip_bot_mention(text: str, username: str | None) -> str:
    """Remove a `@botname` suffix from a leading command, as groups add."""
    if not username or not text.startswith("/"):
        return text
    command, sep, rest = text.partition(" ")
    suffix = f"@{username}"
    if command.endswith(suffix):
        command = command[: -len(suffix)]
    return command + sep + rest


async def _reply_safe(message: Message, text: str) -> None:
    """Reply with Markdown, falling back to plain text if the LLM output
    isn't valid Telegram Markdown (which would otherwise drop the message)."""
    try:
        await message.reply_text(text, parse_mode="Markdown")
    except BadRequest:
        await message.reply_text(text)
