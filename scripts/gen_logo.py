#!/usr/bin/env python3
"""Generate the LeSysBot brand assets from the pixel art below.

The sprites are the single source of truth: every SVG, PNG, ICO and terminal
banner is derived from the same character grids, so the 16px favicon and the
1024px export can never drift apart.

    python3 scripts/gen_logo.py            # write assets/brand/
    python3 scripts/gen_logo.py --banner   # print the mark to the terminal

Pillow is only needed for the raster exports; --banner and the SVGs work
without it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# --- palette -----------------------------------------------------------------
# Six colours, NES-style discipline: one ink, one rim, one cast shadow, and a
# three-step ramp for the burst itself. Every value is a token the docs site
# already ships (--color-brand-* and slate 800/900 in src/styles/main.css), so
# the mark and the site share one palette instead of two that nearly match.
PALETTE = {
    "k": "#0F172A",  # tile ink      (slate-900, the favicon's ground today)
    "e": "#1E293B",  # tile rim, 1px (slate-800)
    "d": "#155E75",  # cast shadow, offset 1px down-right (brand-800)
    "s": "#0891B2",  # burst shade   (brand-600, lower-right faces)
    "b": "#22D3EE",  # burst base    (brand-400)
    "l": "#67E8F9",  # burst light   (brand-300, upper-left faces)
}
TRANSPARENT = "."

# --- sprites -----------------------------------------------------------------
# One character per pixel. Edit these to change the logo; everything else
# follows. Read the palette above for what each character paints.
MARK_32 = (
    "...eeeeeeeeeeeeeeeeeeeeeeeeee..."
    "..ekkkkkkkkkkkkkkkkkkkkkkkkkke.."
    ".ekkkkkkkkkkkkkkkkkkkkkkkkkkkke."
    "ekkkkkkkkkkkkkkllkkkkkkkkkkkkkke"
    "ekkkkkkkkkkkkklbblkkkkkkkkkkkkke"
    "ekkkkkkkkkkkkklbbsdkkkkkkkkkkkke"
    "ekkkkkllkkkkkklbbsdkkkkkllkkkkke"
    "ekkkklbbllkkkklbbsdkkkllbblkkkke"
    "ekkkkklbbblkkklbbsdkklbbbsddkkke"
    "ekkkkkklbbblkklbbsdklbbbsddkkkke"
    "ekkkkkkklbbblklbbsdlbbbsddkkkkke"
    "ekkkkkkkklbbblbbbblbbbsddkkkkkke"
    "ekkkkkkkkklbbbbbbbbbbsddkkkkkkke"
    "ekkkkkkkkkklbbbbbbbbsddkkkkkkkke"
    "ekkkkkkklllbbbbbbbbbblllkkkkkkke"
    "ekkkkkllbbbbbbbbbbbbbbbbllkkkkke"
    "ekkkkklsbbbbbbbbbbbbbbbbssdkkkke"
    "ekkkkkkdlssbbbbbbbbbbsssdddkkkke"
    "ekkkkkkkkddlbbbbbbbbsddddkkkkkke"
    "ekkkkkkkkklbbbbbbbbbblkkkkkkkkke"
    "ekkkkkkkklbbbsbbbbsbbblkkkkkkkke"
    "ekkkkkkklbbbsdlbbsdlbbblkkkkkkke"
    "ekkkkkklbbbsddlbbsdklbbblkkkkkke"
    "ekkkkklbbbsddklbbsdkklbbblkkkkke"
    "ekkkklbbssddkklbbsdkkklsbblkkkke"
    "ekkkkklsdddkkklbbsdkkkkdlsddkkke"
    "ekkkkkkddkkkkklbbsdkkkkkkddkkkke"
    "ekkkkkkkkkkkkklbbsdkkkkkkkkkkkke"
    "ekkkkkkkkkkkkkklsddkkkkkkkkkkkke"
    ".ekkkkkkkkkkkkkkddkkkkkkkkkkkke."
    "..ekkkkkkkkkkkkkkkkkkkkkkkkkke.."
    "...eeeeeeeeeeeeeeeeeeeeeeeeee..."
)

# The favicon cut. Redrawn, not scaled: at 16px the bevel and the cast shadow
# turn to mud, so this one is flat coral with 2px arms.
MARK_16 = (
    ".kkkkkkkkkkkkkk."
    "kkkkkkkbbkkkkkkk"
    "kkkkkkkbbkkkkkkk"
    "kkkbkkkbbkkkbkkk"
    "kkkbbkkbbkkbbkkk"
    "kkkkbbkbbkbbkkkk"
    "kkkkkbbbbbbkkkkk"
    "kkkkbbbbbbbbkkkk"
    "kkkkbbbbbbbbkkkk"
    "kkkkkbbbbbbkkkkk"
    "kkkkbbkbbkbbkkkk"
    "kkkbbkkbbkkbbkkk"
    "kkkbkkkbbkkkbkkk"
    "kkkkkkkbbkkkkkkk"
    "kkkkkkkbbkkkkkkk"
    ".kkkkkkkkkkkkkk."
)

# 5x7 arcade caps — only the letters LESYSBOT needs.
FONT_5X7 = {
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
}
WORDMARK_TEXT = "LESYSBOT"


# --- grid helpers ------------------------------------------------------------
def to_grid(flat: str, width: int) -> list[list[str]]:
    """Split a flat sprite string into rows of `width` characters."""
    rows = [list(flat[i:i + width]) for i in range(0, len(flat), width)]
    assert all(len(r) == width for r in rows), "sprite is not rectangular"
    return rows


def scale_grid(grid: list[list[str]], factor: int) -> list[list[str]]:
    return [[ch for ch in row for _ in range(factor)] for row in grid for _ in range(factor)]


def scanline(grid: list[list[str]]) -> list[list[str]]:
    """CRT variant: darken every other row by swapping down one palette step."""
    dim = {"l": "b", "b": "s", "s": "d", "e": "k", "k": "k", "d": "d", ".": "."}
    return [[dim[ch] if r % 2 else ch for ch in row] for r, row in enumerate(grid)]


def wordmark() -> list[list[str]]:
    """Mark + LESYSBOT on a transparent plate, text at 2x so it stays chunky."""
    mark = to_grid(MARK_32, 32)
    scale, gap, tracking = 2, 10, 4
    glyph_w, glyph_h = 5 * scale, 7 * scale
    text_w = len(WORDMARK_TEXT) * (glyph_w + tracking) - tracking
    width = 32 + gap + text_w + scale  # +scale so the last letter's shadow fits
    height = 32
    grid = [[TRANSPARENT] * width for _ in range(height)]

    for r, row in enumerate(mark):
        for c, ch in enumerate(row):
            grid[r][c] = ch

    top = (height - glyph_h) // 2
    x = 32 + gap
    for letter in WORDMARK_TEXT:
        rows = FONT_5X7[letter]
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                if ch != "#":
                    continue
                for dr in range(scale):
                    for dc in range(scale):
                        y, px = top + r * scale + dr, x + c * scale + dc
                        # 1-unit (2px) drop shadow first, then the letter on top
                        if grid[y + scale][px + scale] == TRANSPARENT:
                            grid[y + scale][px + scale] = "s"
                        grid[y][px] = "b"
        x += glyph_w + tracking
    return grid


# --- emitters ----------------------------------------------------------------
def to_svg(grid: list[list[str]], scale: int = 16) -> str:
    """Pixel-exact SVG: horizontal runs of one colour merge into a single rect."""
    h, w = len(grid), len(grid[0])
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w * scale}" height="{h * scale}" shape-rendering="crispEdges" '
        f'role="img" aria-label="LeSysBot">'
    ]
    for y, row in enumerate(grid):
        x = 0
        while x < w:
            ch = row[x]
            run = 1
            while x + run < w and row[x + run] == ch:
                run += 1
            if ch != TRANSPARENT:
                out.append(
                    f'<rect x="{x}" y="{y}" width="{run}" height="1" fill="{PALETTE[ch]}"/>'
                )
            x += run
    out.append("</svg>")
    return "\n".join(out) + "\n"


def to_image(grid: list[list[str]], scale: int = 1):
    from PIL import Image

    h, w = len(grid), len(grid[0])
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch != TRANSPARENT:
                hex_ = PALETTE[ch].lstrip("#")
                px[x, y] = tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    return im


def to_ansi(grid: list[list[str]]) -> str:
    """Half-block rendering: one terminal cell carries two vertical pixels."""
    def rgb(ch: str) -> tuple[int, int, int]:
        hex_ = PALETTE[ch].lstrip("#")
        return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))

    lines = []
    for y in range(0, len(grid), 2):
        top, bottom = grid[y], grid[y + 1] if y + 1 < len(grid) else [TRANSPARENT] * len(grid[0])
        line = []
        for x in range(len(grid[0])):
            t, b = top[x], bottom[x]
            if t == TRANSPARENT and b == TRANSPARENT:
                line.append("\033[0m ")
            elif t == TRANSPARENT:
                line.append("\033[0m\033[38;2;{};{};{}m▄".format(*rgb(b)))
            elif b == TRANSPARENT:
                line.append("\033[0m\033[38;2;{};{};{}m▀".format(*rgb(t)))
            else:
                line.append(
                    "\033[38;2;{};{};{}m\033[48;2;{};{};{}m▀".format(*rgb(t), *rgb(b))
                )
        lines.append("".join(line) + "\033[0m")
    return "\n".join(lines) + "\n"


# --- assets ------------------------------------------------------------------
PNG_SIZES = (16, 32, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 32, 64, 128, 256)


def build(out_dir: Path) -> list[Path]:
    mark32 = to_grid(MARK_32, 32)
    mark16 = to_grid(MARK_16, 16)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write_text(name: str, text: str) -> None:
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)

    write_text("lesysbot-mark.svg", to_svg(mark32))
    write_text("lesysbot-mark-16.svg", to_svg(mark16, scale=32))
    write_text("lesysbot-mark-scanline.svg", to_svg(scanline(mark32)))
    write_text("lesysbot-wordmark.svg", to_svg(wordmark(), scale=8))
    # banner.txt is the 16-row splash the install script shows after `clear`;
    # banner-small.txt is the 8-row cut for output that has to stay compact.
    write_text("banner.txt", to_ansi(mark32))
    write_text("banner-small.txt", to_ansi(mark16))

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("! Pillow not installed — skipped PNG/ICO exports", file=sys.stderr)
        return written

    for size in PNG_SIZES:
        # 16px gets the redrawn cut; everything else is a clean multiple of 32.
        grid = mark16 if size == 16 else mark32
        img = to_image(grid, scale=size // len(grid))
        path = out_dir / f"lesysbot-mark-{size}.png"
        img.save(path)
        written.append(path)

    img = to_image(wordmark(), scale=8)
    img.save(out_dir / "lesysbot-wordmark.png")
    written.append(out_dir / "lesysbot-wordmark.png")

    # Build every ICO frame at its native scale so Pillow never resamples one.
    # It skips any requested size larger than the base image and only reuses a
    # provided frame on an exact size match, so the base has to be the largest.
    frames = [
        to_image(mark16 if s == 16 else mark32, scale=s // (16 if s == 16 else 32))
        for s in sorted(ICO_SIZES, reverse=True)
    ]
    ico = out_dir / "lesysbot.ico"
    frames[0].save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                   append_images=frames[1:])
    written.append(ico)
    return written


def write_package_module(repo_root: Path) -> Path | None:
    """Emit the sprites into the package so the CLI and web UI can draw them.

    `assets/` sits outside the package on purpose (it must not bloat the wheel),
    so an installed or PyInstaller-frozen copy can't read it. Same fix the
    control panel uses in `management/page.py`: inline the asset as Python. Only
    the grids go in — `core/banner.py` renders `MARK` (16px) through Rich, and
    `management/page.py` renders `MARK_32` to SVG for the panel header, each from
    the same sprite so the copies can't drift.
    """
    target = repo_root / "lesysbot" / "core" / "_logo.py"
    if not target.parent.is_dir():
        return None

    def grid_literal(name: str, flat: str, width: int) -> str:
        rows = "\n".join(f'    "{"".join(row)}",' for row in to_grid(flat, width))
        return f"{name} = (\n{rows}\n)\n"

    palette = "\n".join(f'    "{k}": "{v}",' for k, v in PALETTE.items())
    target.write_text(
        '"""The LeSysBot mark, one character per pixel.\n\n'
        "Generated by scripts/gen_logo.py — do not edit by hand. Change the sprite\n"
        "there and rerun it; see assets/brand/README.md. ``MARK`` is the 16px cut\n"
        "(terminal banner + favicon); ``MARK_32`` is the bevelled 32px mark.\n"
        '"""\n\n'
        f"{grid_literal('MARK', MARK_16, 16)}\n"
        f"{grid_literal('MARK_32', MARK_32, 32)}\n"
        f"PALETTE = {{\n{palette}\n}}\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--out", type=Path, default=root / "assets" / "brand",
                    help="output directory (default: assets/brand)")
    ap.add_argument("--banner", action="store_true",
                    help="print the mark to stdout and exit")
    ap.add_argument("--small", action="store_true",
                    help="with --banner, use the compact 16px cut")
    args = ap.parse_args()

    if args.banner:
        grid = to_grid(MARK_16, 16) if args.small else to_grid(MARK_32, 32)
        sys.stdout.write(to_ansi(grid))
        return 0

    written = build(args.out)
    module = write_package_module(root)
    if module:
        written.append(module)
    for path in written:
        print(f"  {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print(f"\n{len(written)} files written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
