"""The terminal mark: it must decode back to the sprite, and stay in sync with it."""
import importlib.util
from pathlib import Path

import pytest
from rich.console import Console
from rich.text import Text

from lesysbot.core._logo import MARK, MARK_32, PALETTE
from lesysbot.core.banner import LOWER_HALF, UPPER_HALF, banner, render, should_draw

TRANSPARENT = "."
REPO = Path(__file__).resolve().parent.parent


def _console() -> Console:
    return Console(force_terminal=True, color_system="truecolor", width=80)


def _decode(text: Text) -> list[list[str]]:
    """Rebuild the pixel grid from what a terminal would actually be sent."""
    hex_to_char = {v.lower(): k for k, v in PALETTE.items()}

    def char_for(colour) -> str:
        if colour is None:
            return TRANSPARENT
        return hex_to_char["#" + colour.triplet.hex.lstrip("#").lower()]

    grid: list[list[str]] = []
    top_row: list[str] = []
    bottom_row: list[str] = []
    for segment in _console().render(text):
        if segment.control:
            continue
        for glyph in segment.text:
            if glyph == "\n":
                grid.extend([top_row, bottom_row])
                top_row, bottom_row = [], []
                continue
            style = segment.style
            if glyph == UPPER_HALF:
                top_row.append(char_for(style.color))
                bottom_row.append(char_for(style.bgcolor))
            elif glyph == LOWER_HALF:
                top_row.append(TRANSPARENT)
                bottom_row.append(char_for(style.color))
            else:
                top_row.append(TRANSPARENT)
                bottom_row.append(TRANSPARENT)
    if top_row:
        grid.extend([top_row, bottom_row])
    return grid


def test_render_round_trips_to_the_sprite():
    decoded = _decode(render())
    assert ["".join(row) for row in decoded] == list(MARK)


def test_render_is_half_height():
    """One terminal cell carries two pixel rows, so the mark stays square."""
    lines = render().plain.split("\n")
    assert len(lines) == len(MARK) // 2
    assert {len(line) for line in lines} == {len(MARK[0])}


def test_transparent_top_uses_the_lower_half_block():
    """A background colour fills the whole cell, which would square off the
    tile's cut corners — the corners must be drawn with a foreground instead."""
    first = render().plain.split("\n")[0]
    assert MARK[0][0] == TRANSPARENT and MARK[1][0] != TRANSPARENT
    assert first[0] == LOWER_HALF


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"force_terminal": True, "color_system": "truecolor"}, True),
        ({"force_terminal": False}, False),
        ({"force_terminal": True, "no_color": True}, False),
        ({"force_terminal": True, "color_system": None}, False),
    ],
)
def test_should_draw_only_on_a_colour_terminal(kwargs, expected):
    assert should_draw(Console(**kwargs)) is expected


def test_banner_returns_none_when_it_should_not_draw():
    assert banner(Console(force_terminal=False)) is None
    assert banner(_console()) is not None


def test_generated_module_matches_the_generator():
    """`_logo.py` is generated; a hand-edit to either side must fail here."""
    spec = importlib.util.spec_from_file_location("gen_logo", REPO / "scripts" / "gen_logo.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    assert gen.PALETTE == PALETTE, "palette drifted — rerun scripts/gen_logo.py"
    rows = ["".join(row) for row in gen.to_grid(gen.MARK_16, 16)]
    assert rows == list(MARK), "sprite drifted — rerun scripts/gen_logo.py"
    rows32 = ["".join(row) for row in gen.to_grid(gen.MARK_32, 32)]
    assert rows32 == list(MARK_32), "32px sprite drifted — rerun scripts/gen_logo.py"
