from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Any, Callable

from watchfiles import awatch

from lesysbot.core import notify
from lesysbot.core.config import Settings
from lesysbot.core.trace import TraceWriter
from lesysbot.core.types import ConfirmCallback, ConversationHistory, Message, Role
from lesysbot.llm.client import LLMClient
from lesysbot.mcp.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Returned when the LLM finishes a turn with no tool call and no answer text and
# there is nothing better to show. Local models do this intermittently: a
# reasoning model can put everything in its thinking channel, and some (observed
# with qwen3.5 via Ollama on the turn that summarises a tool result) just stream
# zero tokens and stop. Without this, `handle()` would return "", which some
# adapters (Telegram rejects empty messages) silently drop, so the user sees no
# reply at all.
_EMPTY_REPLY_FALLBACK = (
    "I couldn't generate a reply for that — please try rephrasing your question."
)


class Agent:
    """Orchestrates the message → LLM → tools → reply loop."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings.llm)
        self._registry = ToolRegistry()
        self._histories: dict[str, ConversationHistory] = {}
        # One turn at a time per user — see `_turn_lock`.
        self._turn_locks: dict[str, asyncio.Lock] = {}
        self._reload_lock = asyncio.Lock()
        self._confirm_fn: ConfirmCallback | None = None
        self._tracer: TraceWriter | None = (
            TraceWriter(
                settings.logging.trace_file,
                when=settings.logging.when,
                backup_count=settings.logging.backup_count,
            )
            if settings.logging.trace_file
            else None
        )

    def set_confirm_fn(self, fn: ConfirmCallback) -> None:
        self._confirm_fn = fn

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def llm(self) -> LLMClient:
        return self._llm

    @property
    def settings(self) -> Settings:
        return self._settings

    async def aclose(self) -> None:
        """Close the LLM's httpx client before the event loop is torn down, so it
        isn't finalized on a closed loop ('Event loop is closed')."""
        await self._llm.aclose()

    async def setup(self) -> None:
        # Wire the persisted enable/disable state before loading tools so disabled
        # tools are applied from the first request (`lesysbot tools` mutates this set).
        self._registry.set_state_path(self._settings.mcp.state_file)
        self._registry.load_state()
        self._registry.load_directory(self._settings.mcp.tools_dir)
        logger.info("Tools loaded: %s", self._registry.names)

        if self._settings.mcp.hot_reload:
            asyncio.create_task(self._watch_tools())
        asyncio.create_task(self._watch_tool_state())

    async def _watch_tool_state(self) -> None:
        """Re-read the enable/disable state when another process rewrites it.

        The disabled set lives in this process's registry, but two other things
        write the file it's persisted to: ``lesysbot tools enable/disable`` and
        any editor. Without this watch those changes only took effect on the next
        restart, which is a confusing thing to explain to someone who just ran an
        enable/disable command.

        Watched unconditionally — it's about *other* processes, so it isn't tied
        to ``mcp.hot_reload`` (which governs re-importing tool code).
        """
        state_path = self._settings.mcp.state_file
        if not state_path:
            return
        state_file = Path(state_path)
        # Watch the directory, not the file: the file may not exist yet, and a
        # watch on a missing path raises.
        watch_dir = state_file.parent
        if not watch_dir.exists():
            return
        logger.info("Watching %s for tool enable/disable changes...", state_file)
        async for changes in awatch(watch_dir, watch_filter=_state_file_only(state_file)):
            logger.info("Tool state changed (%d event(s)) — reloading it.", len(changes))
            self._registry.load_state()

    async def _watch_tools(self) -> None:
        tools_path = Path(self._settings.mcp.tools_dir)
        if not tools_path.exists():
            return
        logger.info("Watching %s for tool changes...", tools_path)
        async for _ in awatch(tools_path, watch_filter=_py_files_only):
            async with self._reload_lock:
                logger.info("Tool files changed — reloading...")
                self._registry.reload(tools_path)

    def _get_history(self, user_id: str) -> ConversationHistory:
        if user_id not in self._histories:
            h = ConversationHistory(max_size=self._settings.agent.max_history)
            h.add(Message(role=Role.SYSTEM, content=self._settings.agent.system_prompt))
            self._histories[user_id] = h
        return self._histories[user_id]

    async def handle(
        self,
        user_id: str,
        text: str,
        on_token: Callable[[str], None] | None = None,
        *,
        on_reasoning: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        # Stamp the requester so tools can push follow-up messages to them via
        # core/notify (covers both the slash path and the LLM tool-call path).
        notify.set_current_user(user_id)

        if text.startswith("/"):
            # Slash commands dispatch straight to a tool and never touch the
            # conversation history, so they deliberately skip the turn lock:
            # `/cancel_shutdown` has to stay answerable *while* the LLM turn
            # that scheduled the reboot is still running.
            return await self._handle_slash(text, user_id)

        async with self._turn_lock(user_id):
            return await self._run_turn(
                user_id,
                text,
                on_token,
                on_reasoning=on_reasoning,
                on_status=on_status,
            )

    def _turn_lock(self, user_id: str) -> asyncio.Lock:
        """Serialize LLM turns per user — a conversation is a single thread.

        Remote adapters dispatch updates concurrently (Telegram needs
        ``concurrent_updates(True)`` for the confirmation flow to work at all),
        so a message arriving while a turn was still running started a *second*
        `handle()` against the same `ConversationHistory`. The two loops then
        appended into one list and each re-sent it: every LLM call saw the other
        conversation's messages spliced into its own, read the resulting
        interleaving as a tool call still awaiting its result, and ran the tool
        again — so one request executed `reboot`/`share_dashboard` several times
        and both loops replied, each quoting the other's results.

        Confirmations make it easy to hit: `confirm()` parks the turn for up to
        five minutes waiting on a button, and typing another message instead of
        tapping is the obvious thing to do.
        """
        lock = self._turn_locks.get(user_id)
        if lock is None:
            # No await between the miss and the insert, so this can't race.
            lock = self._turn_locks[user_id] = asyncio.Lock()
        return lock

    async def _run_turn(
        self,
        user_id: str,
        text: str,
        on_token: Callable[[str], None] | None = None,
        *,
        on_reasoning: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        history = self._get_history(user_id)
        history.add(Message(role=Role.USER, content=text))

        tools = self._registry.get_openai_schemas()
        max_tool_calls = self._settings.agent.max_tool_calls

        trace = (
            self._tracer.start(user_id, text, self._settings.llm.model)
            if self._tracer
            else None
        )

        # Results of the most recent tool batch, kept so an empty final turn can
        # fall back to them instead of discarding work the user asked for.
        last_tool_results: list[str] = []

        try:
            for _ in range(max_tool_calls + 1):
                messages = history.to_list()
                if trace:
                    trace.begin_llm(len(messages))

                if on_status:
                    on_status("Thinking…")

                # Pass on_token only for potential final text response;
                # tool-call iterations produce no text so it won't fire there.
                response = await self._llm.chat(
                    messages,
                    tools=tools or None,
                    on_token=on_token,
                    on_reasoning=on_reasoning,
                )
                history.add(response)

                if not response.tool_calls:
                    content = response.content or ""
                    if content.strip():
                        reply = content
                    elif last_tool_results:
                        # The tools ran and produced the answer; only the model's
                        # summarising turn came back empty. Show the raw results
                        # rather than an apology that throws them away — LeSysBot
                        # tools return chat-ready text by design.
                        reply = "\n\n".join(last_tool_results)
                    else:
                        reply = _EMPTY_REPLY_FALLBACK
                    if trace:
                        trace.end_llm("text")
                        trace.finish(reply)
                    return reply

                if trace:
                    trace.end_llm("tool_calls")

                if on_status:
                    names = ", ".join(tc.name for tc in response.tool_calls)
                    on_status(f"Running {names}…")

                # Execute tool calls — sequential when any needs confirmation,
                # parallel otherwise.
                any_needs_confirm = self._confirm_fn and any(
                    (self._registry.get_tool_meta(tc.name) or {}).get("confirm")
                    for tc in response.tool_calls
                )

                if any_needs_confirm:
                    outcomes: list[tuple[str, float]] = []
                    for tc in response.tool_calls:
                        meta = self._registry.get_tool_meta(tc.name) or {}
                        confirm_val = meta.get("confirm")
                        if confirm_val and self._confirm_fn:
                            prompt = (
                                confirm_val
                                if isinstance(confirm_val, str)
                                else f"Run `{tc.name}`?"
                            )
                            approved = await self._confirm_fn(
                                user_id, tc.name, prompt, tc.arguments
                            )
                            if not approved:
                                outcomes.append(("Cancelled by user.", 0.0))
                                continue
                        outcomes.append(await _timed_tool(self._registry, tc.name, tc.arguments))
                else:
                    outcomes = list(
                        await asyncio.gather(
                            *[
                                _timed_tool(self._registry, tc.name, tc.arguments)
                                for tc in response.tool_calls
                            ]
                        )
                    )

                last_tool_results = [result for result, _ in outcomes]

                for tc, (result, duration_ms) in zip(response.tool_calls, outcomes):
                    if trace:
                        trace.add_tool(tc.name, tc.arguments, result, duration_ms)
                    history.add(Message(role=Role.TOOL, content=result, tool_call_id=tc.id))

        except Exception as e:
            # Handled, user-facing condition (e.g. backend unreachable) — keep the
            # console clean with a one-line error; full traceback only under -v/DEBUG.
            logger.error("LLM error: %s", e)
            logger.debug("LLM error detail", exc_info=True)
            if trace:
                trace.finish("", error=str(e))
            return (
                f"LLM unavailable: {e}\n\n"
                "You can still use tools directly — type /help to see available commands."
            )

        reply = "I reached the maximum number of tool calls. Please try rephrasing."
        if trace:
            trace.finish(reply)
        return reply

    async def _handle_slash(self, text: str, user_id: str) -> str:
        """Dispatch a /command directly to a tool or built-in — no LLM needed."""
        try:
            parts = shlex.split(text[1:])
        except ValueError:
            parts = text[1:].split()

        if not parts:
            return self._registry.list_tools_text()

        cmd = parts[0].lower()
        raw_args = parts[1:]

        # Built-in meta-commands
        if cmd in ("help", "tools"):
            return self._registry.list_tools_text()

        if cmd == "clear":
            self.clear_history(user_id)
            return "Conversation history cleared."

        if cmd == "history":
            return self._format_history(user_id)

        # Tool dispatch
        info = self._registry.get_tool_info(cmd)
        if info is None:
            return (
                f"Unknown command: /{cmd}\n\n"
                + self._registry.list_tools_text()
            )

        kwargs = _parse_args(raw_args, info["param_names"])

        missing = [p for p in info["required"] if p not in kwargs]
        if missing:
            return _usage(info, missing)

        return await self._registry.call(cmd, kwargs)

    def _format_history(self, user_id: str) -> str:
        history = self._histories.get(user_id)
        if not history or not history.messages:
            return "No conversation history."
        lines = []
        for msg in history.messages:
            if msg.role == Role.SYSTEM:
                continue
            label = msg.role.value.upper()
            body = msg.content
            if len(body) > 300:
                body = body[:300] + "…"
            lines.append(f"{label}: {body}")
        return "\n\n".join(lines) if lines else "No messages yet."

    def clear_history(self, user_id: str) -> None:
        self._histories.pop(user_id, None)


def _py_files_only(change: object, path: str) -> bool:
    return path.endswith(".py")


def _state_file_only(state_file: Path):
    """watchfiles filter matching just the tool-state file in its directory.

    Matches on the file *name* rather than the full path: the watch is already
    scoped to one directory, and comparing paths would have to resolve symlinks
    on both sides to be reliable (``~/.lesysbot`` is a symlink on some setups).
    """
    target = state_file.name

    def _filter(change: object, path: str) -> bool:
        return Path(path).name == target

    return _filter


async def _timed_tool(
    registry: ToolRegistry, name: str, arguments: dict[str, Any]
) -> tuple[str, float]:
    t0 = time.perf_counter()
    result = await registry.call(name, arguments)
    return result, (time.perf_counter() - t0) * 1000


def _parse_args(raw: list[str], param_names: list[str]) -> dict[str, Any]:
    """Map raw string tokens to tool parameter names.

    Supports two styles:
      named:      key=value  or  key="value with spaces"
      positional: values are assigned to params in declaration order
    """
    if raw and "=" in raw[0]:
        kwargs: dict[str, Any] = {}
        for token in raw:
            k, _, v = token.partition("=")
            kwargs[k.strip()] = v.strip()
        return kwargs
    # positional
    return {name: val for name, val in zip(param_names, raw)}


def _usage(info: dict[str, Any], missing: list[str]) -> str:
    params = info["param_names"]
    required = info["required"]
    parts = [f"<{p}>" if p in required else f"[{p}]" for p in params]
    sig = " ".join(parts)
    lines = [
        f"Missing required parameter(s): {', '.join(missing)}",
        "",
        f"Usage: /{info['name']} {sig}".rstrip(),
        f"  {info['description']}",
    ]
    if len(params) > 1:
        lines += ["", "You can also use named parameters:  key=value"]
    return "\n".join(lines)
