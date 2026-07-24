"""Draw the LeSysBot mark in a terminal.

The sprite lives in `_logo.py`, generated from `scripts/gen_logo.py`. Rendering
goes through Rich rather than raw escape codes so the colour downgrades on its
own for 256- and 16-colour terminals, and drops out entirely under `NO_COLOR`,
a dumb `TERM`, or a redirected stdout — the same rules the rest of the CLI
already plays by.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lesysbot.core._logo import MARK, PALETTE

if TYPE_CHECKING:
    from rich.console import Console
    from rich.text import Text

TRANSPARENT = "."
UPPER_HALF = "▀"
LOWER_HALF = "▄"


def render() -> Text:
    """The mark as Rich text: one cell per two vertical pixels, via half-blocks.

    Each cell picks the glyph that leaves no colour where the sprite is
    transparent — a background colour fills the whole cell, so a half-block's
    *foreground* is the only way to paint one half and leave the other clear.
    That's what keeps the tile's cut corners from squaring off.
    """
    from rich.text import Text

    out = Text()
    for y in range(0, len(MARK), 2):
        top = MARK[y]
        bottom = MARK[y + 1] if y + 1 < len(MARK) else TRANSPARENT * len(top)
        for x, t in enumerate(top):
            b = bottom[x]
            if t == TRANSPARENT and b == TRANSPARENT:
                out.append(" ")
            elif t == TRANSPARENT:
                out.append(LOWER_HALF, style=PALETTE[b])
            elif b == TRANSPARENT:
                out.append(UPPER_HALF, style=PALETTE[t])
            else:
                out.append(UPPER_HALF, style=f"{PALETTE[t]} on {PALETTE[b]}")
        out.append("\n")
    out.rstrip()  # in place; Text.rstrip returns None
    return out


def should_draw(console: Console) -> bool:
    """False when the output isn't a colour terminal a human is looking at."""
    return console.is_terminal and not console.no_color and console.color_system is not None


def banner(console: Console) -> Text | None:
    """The mark, or None when this console shouldn't get one."""
    return render() if should_draw(console) else None
