from __future__ import annotations

import asyncio
import re
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.text import Text

from lesysbot.messaging.base import MessageHandler, MessagingAdapter

console = Console()
USER_ID = "cli-user"

_HELP_TEXT = (
    "[bold]Built-in commands[/]\n"
    "  [cyan]exit[/] / [cyan]quit[/]   Exit the bot\n"
    "  [cyan]/help[/]          List available tools\n"
    "  [cyan]/clear[/]         Clear conversation history\n"
    "  [cyan]/history[/]       Show recent conversation\n\n"
    "[bold]Tool commands[/] (no LLM needed)\n"
    "  [cyan]/tool_name arg1 arg2[/]       positional\n"
    "  [cyan]/tool_name key=value[/]       named\n"
)

# Reasoning models (e.g. Qwen) emit their chain-of-thought inline as
# <think>…</think>. Split that out from the visible answer so we can render it
# separately (dim) instead of dumping raw tags into the Markdown.
_THINK_CLOSED = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>(.*)$", re.DOTALL)


def _split_think(raw: str) -> tuple[str, str]:
    """Return (reasoning, answer) from raw streamed content."""
    reasoning = "".join(_THINK_CLOSED.findall(raw))
    answer = _THINK_CLOSED.sub("", raw)
    m = _THINK_OPEN.search(answer)
    if m:  # an unclosed <think> still streaming
        reasoning += m.group(1)
        answer = answer[: m.start()]
    return reasoning, answer


class CLIAdapter(MessagingAdapter):
    """Interactive terminal adapter with streaming, rendered Markdown output."""

    def __init__(self) -> None:
        # The currently-active Live display, if any — so confirm() can pause it.
        self._live: Live | None = None

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        # Pause any live streaming display so the prompt renders cleanly.
        live = self._live
        if live is not None:
            live.stop()

        loop = asyncio.get_event_loop()
        args_str = "  " + "\n  ".join(f"{k} = {v!r}" for k, v in args.items()) if args else ""
        console.print("\n[bold yellow]⚠ Confirmation required[/]")
        console.print(f"  Tool : [cyan]{tool_name}[/]")
        if args_str:
            console.print(args_str)
        console.print(f"  {prompt}")
        answer = await loop.run_in_executor(
            None,
            lambda: Prompt.ask("Proceed?", choices=["y", "n"], default="n"),
        )

        if live is not None:
            live.start()
        return answer.lower() == "y"

    def _print_header(self) -> None:
        """Branded header: the mark beside the name/version, or a plain line when
        the terminal can't take colour — the same rule the status screen uses."""
        from rich.table import Table

        from lesysbot.core.banner import banner
        from lesysbot.core.status import _version

        mark = banner(console)
        console.print()
        if mark:
            head = Table.grid(padding=(0, 3))
            head.add_column()
            head.add_column(vertical="middle")
            head.add_row(
                mark,
                f"[bold green]LeSysBot[/] [dim]v{_version()}[/]\n"
                "[dim]local AI assistant with tools[/]",
            )
            console.print(head)
        else:
            console.print(f"[bold green]LeSysBot[/] [dim]v{_version()}[/] — local AI assistant with tools")
        console.print(
            "[dim]Type a message to chat, or use /commands directly. Type 'exit' to quit.[/]\n"
        )
        console.print(_HELP_TEXT)

    async def start(self, handler: MessageHandler) -> None:
        self._print_header()

        loop = asyncio.get_event_loop()

        while True:
            try:
                text = await loop.run_in_executor(None, lambda: Prompt.ask("[bold cyan]You[/]"))
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Bye![/]")
                break

            stripped = text.strip()
            if not stripped:
                continue
            if stripped.lower() in ("exit", "quit", "q"):
                console.print("[dim]Bye![/]")
                break

            # Slash commands / direct tool calls: no LLM, no Markdown — show a
            # spinner while they run, then print the result verbatim (tool output
            # contains <param> signatures and column whitespace Markdown mangles).
            if stripped.startswith("/"):
                try:
                    with console.status("[cyan]Working…[/]", spinner="dots"):
                        reply = await handler(USER_ID, stripped)
                except Exception as e:
                    console.print(f"\n[bold red]Error:[/] {e}\n")
                    continue
                console.print("\n[bold green]Bot[/]")
                console.print(reply, markup=False, highlight=False)
                console.print()
                continue

            # LLM turn: stream with a thinking spinner, dim reasoning, and live
            # rendered Markdown for the answer.
            raw_content = ""       # streamed answer text (may contain <think>…)
            reasoning_stream = ""  # reasoning_content from reasoning-model APIs
            finished = False
            spinner = Spinner("dots", text=Text("Thinking…", style="cyan"))

            def render() -> Group:
                think, answer = _split_think(raw_content)
                reasoning = (reasoning_stream + think).strip()
                parts: list[Any] = []
                if reasoning:
                    parts.append(Text("✳ Thinking", style="dim italic"))
                    parts.append(Text(reasoning, style="dim"))
                if answer.strip():
                    parts.append(Text("Bot", style="bold green"))
                    parts.append(Markdown(answer))
                if not finished and not answer.strip():
                    parts.append(spinner)
                return Group(*parts)

            def on_status(msg: str) -> None:
                spinner.update(text=Text(msg, style="cyan"))
                if self._live is not None:
                    self._live.update(render())

            def on_reasoning(chunk: str) -> None:
                nonlocal reasoning_stream
                reasoning_stream += chunk
                if self._live is not None:
                    self._live.update(render())

            def on_token(chunk: str) -> None:
                nonlocal raw_content
                raw_content += chunk
                if self._live is not None:
                    self._live.update(render())

            error: Exception | None = None
            reply = ""
            with Live(
                console=console,
                auto_refresh=True,
                refresh_per_second=12,
                vertical_overflow="visible",
            ) as live:
                self._live = live
                live.update(render())
                try:
                    reply = await handler(
                        USER_ID,
                        stripped,
                        on_token=on_token,
                        on_reasoning=on_reasoning,
                        on_status=on_status,
                    )
                except Exception as e:
                    error = e
                finished = True
                live.update(render())
            self._live = None

            if error is not None:
                console.print(f"\n[bold red]Error:[/] {error}\n")
                continue

            # If nothing streamed (e.g. "LLM unavailable" fallback), the Live had
            # nothing to show — print the reply verbatim instead.
            if not raw_content.strip() and not reasoning_stream.strip():
                console.print("\n[bold green]Bot[/]")
                console.print(reply, markup=False, highlight=False)
            console.print()

    async def send(self, user_id: str, text: str) -> None:
        console.print(f"\n[bold yellow]Bot:[/]\n{text}\n")
