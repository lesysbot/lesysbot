"""Terminal UI primitives for the setup wizard.

Two implementations behind one duck-typed interface:

- :class:`InteractiveUI` — Rich panels driven by raw keystrokes: ↑/↓ move,
  Enter/→ confirm, number keys jump, ←/Esc takes a menu's "← …" back entry,
  and Esc at a text prompt returns ``None`` so the calling step can go back.
  Widgets render in a transient ``Live`` and leave a one-line summary of the
  answer behind, so scrollback stays compact.
- :class:`PlainUI` — numbered "type a number" menus and plain prompts for
  piped/CI input (the behaviour the shell installers always had). EOF answers
  with the default and sets :attr:`PlainUI.eof` so required-input loops can
  abort instead of spinning forever.

``make_ui()`` picks one based on whether stdin/stdout are terminals.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

ACCENT = "cyan"
_CSI_PARTIAL = re.compile(r"\[[0-9;]*\Z")


def _read_byte(fd: int) -> str:
    """One keyboard character via os.read — NOT sys.stdin, whose readahead
    buffers bytes where select() can't see them and desyncs escape parsing."""
    b = os.read(fd, 1)
    if not b:
        raise EOFError("terminal closed")
    lead = b[0]
    if lead < 0x80:
        return chr(lead)
    # UTF-8 continuation for typed multibyte characters.
    need = 1 if lead < 0xE0 else 2 if lead < 0xF0 else 3
    for _ in range(need):
        b += os.read(fd, 1)
    return b.decode("utf-8", errors="replace")


@contextmanager
def raw_mode():
    """cbreak for the duration of one widget's key loop.

    Held for the whole widget, NOT per keypress: toggling the mode between
    keys lets pending bytes fall into the canonical line buffer, where they
    are lost on the switch back — fast typing (or paste) would keep only the
    first character. cbreak (not full raw) keeps Ctrl-C delivering SIGINT.
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """Blocking read of one keypress (inside :func:`raw_mode`)."""
    import select

    fd = sys.stdin.fileno()
    ch = _read_byte(fd)
    if ch != "\x1b":
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x7f", "\x08"):
            return "backspace"
        return ch
    # Escape sequences can arrive byte-by-byte (multiplexers, remote
    # terminals) — collect with a lenient per-byte timeout, and slurp
    # whole CSI sequences so Home/Del/F-keys can't leak trailing bytes.
    seq = ""
    while select.select([fd], [], [], 0.25)[0]:
        seq += _read_byte(fd)
        if not (seq == "O" or _CSI_PARTIAL.match(seq)):
            break
    if seq in ("[A", "OA"):
        return "up"
    if seq in ("[B", "OB"):
        return "down"
    if seq in ("[C", "OC"):
        return "right"
    if seq in ("[D", "OD"):
        return "left"
    if seq == "":
        return "esc"
    return "ignore"


def _back_index(options: list[str]) -> int | None:
    for i, opt in enumerate(options):
        if opt.startswith("←"):
            return i
    return None


class InteractiveUI:
    """Rich-panel widgets driven by raw keystrokes."""

    interactive = True
    eof = False  # interactive terminals don't run dry mid-wizard

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(highlight=False)

    # ── output helpers ────────────────────────────────────────────────────
    def say(self, text: str = "", style: str | None = None) -> None:
        self.console.print(text, style=style)

    def note(self, text: str) -> None:
        self.console.print(f"  {text}", style="dim")

    def ok(self, text: str) -> None:
        self.console.print(f"  [green]✓[/green]  {text}")

    def warn(self, text: str) -> None:
        self.console.print(f"  [yellow]![/yellow]  {text}")

    def echo_answer(self, label: str, value: str) -> None:
        self.console.print(f"  [{ACCENT}]❯[/{ACCENT}] {label} · [bold]{value}[/bold]")

    # ── widgets ───────────────────────────────────────────────────────────
    def menu(self, title: str, options: list[str], default: int = 1) -> int:
        """Single choice; returns the 1-based option number."""
        back = _back_index(options)
        sel = default - 1
        if not 0 <= sel < len(options):
            sel = 0
        hint = "↑↓ move · ⏎ select · numbers jump"
        if back is not None:
            hint += " · ←/Esc back"

        def render() -> Panel:
            rows = []
            for i, opt in enumerate(options):
                if i == sel:
                    rows.append(Text(f" ❯ {opt} ", style=f"bold {ACCENT}"))
                else:
                    rows.append(Text(f"   {opt} "))
            return Panel(
                Group(*rows),
                title=f"[bold]{title}[/bold]",
                title_align="left",
                subtitle=f"[dim]{hint}[/dim]",
                subtitle_align="right",
                box=box.ROUNDED,
                border_style=ACCENT,
                padding=(1, 2),
            )

        with raw_mode(), Live(render(), console=self.console, transient=True, auto_refresh=False) as live:
            while True:
                key = read_key()
                if key == "enter" or key == "right":
                    break
                if key == "up":
                    sel = (sel - 1) % len(options)
                elif key == "down":
                    sel = (sel + 1) % len(options)
                elif key in ("left", "esc") and back is not None:
                    sel = back
                    break
                elif len(key) == 1 and key.isdigit() and 1 <= int(key) <= len(options):
                    sel = int(key) - 1
                live.update(render(), refresh=True)
        self.echo_answer(title, options[sel])
        return sel + 1

    def text(self, prompt: str, default: str = "", secret: bool = False) -> str | None:
        """Free-text input; returns the value, or ``None`` when Esc backs out.

        With ``secret=True`` the typed characters, the shown default, and the
        left-behind echo are masked with ``*`` so a password never appears on
        screen or in scrollback.
        """
        buf = ""
        hint = "⏎ accept · Esc back"
        title = f"[bold]{prompt}[/bold]"
        if default:
            shown_default = "*" * len(default) if secret else default
            title += f"  [dim]\\[{shown_default}][/dim]"

        def render() -> Panel:
            display = "*" * len(buf) if secret else buf
            line = Text(f" {display}")
            line.append("▌", style=ACCENT)
            return Panel(
                line,
                title=title,
                title_align="left",
                subtitle=f"[dim]{hint}[/dim]",
                subtitle_align="right",
                box=box.ROUNDED,
                border_style=ACCENT,
                padding=(0, 2),
            )

        with raw_mode(), Live(render(), console=self.console, transient=True, auto_refresh=False) as live:
            while True:
                key = read_key()
                if key == "enter":
                    break
                if key == "esc":
                    return None
                if key == "backspace":
                    buf = buf[:-1]
                elif len(key) == 1 and key.isprintable():
                    buf += key
                live.update(render(), refresh=True)
        value = buf or default
        if secret:
            shown = "*" * len(value) if value else "(empty)"
        else:
            shown = value if value else "(empty)"
        self.echo_answer(prompt, shown)
        return value

    def confirm_yn(self, prompt: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        self.console.print(f"  [{ACCENT}]?[/{ACCENT}]  {prompt} [bold]\\[{hint}][/bold]: ", end="")
        try:
            answer = input().strip().lower()
        except EOFError:
            self.console.print()
            return default
        if not answer:
            return default
        return answer.startswith("y")


class PlainUI:
    """Numbered menus + plain prompts for piped/CI input (no keystroke UI)."""

    interactive = False

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(highlight=False)
        self.eof = False

    say = InteractiveUI.say
    note = InteractiveUI.note
    ok = InteractiveUI.ok
    warn = InteractiveUI.warn

    def _input(self, prompt: str, default: str) -> str:
        self.console.print(prompt, end="")
        try:
            answer = input().strip()
        except EOFError:
            self.console.print()
            self.eof = True
            return default
        return answer or default

    def menu(self, title: str, options: list[str], default: int = 1) -> int:
        self.console.print(f"  [bold]{title}[/bold]")
        for i, opt in enumerate(options, 1):
            self.console.print(f"    {i}) {opt}")
        raw = self._input(f"  [{ACCENT}]?[/{ACCENT}]  Choice [bold]\\[{default}][/bold]: ", str(default))
        try:
            choice = int(raw)
        except ValueError:
            return default
        return choice if 1 <= choice <= len(options) else default

    def text(self, prompt: str, default: str = "", secret: bool = False) -> str | None:
        shown_default = "*" * len(default) if (secret and default) else default
        shown = f" [bold]\\[{shown_default}][/bold]" if default else ""
        if secret:
            # No terminal (PlainUI is the non-tty path), so there is nothing to
            # echo the typed password to; still read it without printing it back.
            import getpass

            self.console.print(f"  [{ACCENT}]?[/{ACCENT}]  {prompt}{shown}: ", end="")
            try:
                answer = getpass.getpass("")
            except (EOFError, OSError):  # no tty / closed input → take default
                self.console.print()
                self.eof = True
                return default
            return answer or default
        return self._input(f"  [{ACCENT}]?[/{ACCENT}]  {prompt}{shown}: ", default)

    def confirm_yn(self, prompt: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        raw = self._input(f"  [{ACCENT}]?[/{ACCENT}]  {prompt} [bold]\\[{hint}][/bold]: ", "")
        if not raw:
            return default
        return raw.lower().startswith("y")


def make_ui() -> InteractiveUI | PlainUI:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return InteractiveUI()
    return PlainUI()
