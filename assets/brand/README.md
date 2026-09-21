# LeSysBot brand assets

An 8-bit starburst built like the Claude Code mark and coloured like LeSysBot:
hand-placed pixels, a hard 1px cast shadow, and a rounded ink tile with the
corners cut on the grid rather than with an SVG corner radius.

Everything here is generated from the character grids in
[`scripts/gen_logo.py`](../../scripts/gen_logo.py) — **this README is the only
hand-written file in the folder.** Don't edit the SVGs or PNGs; edit the sprite
and regenerate:

```bash
python3 scripts/gen_logo.py            # rewrite this folder
python3 scripts/gen_logo.py --banner   # print the mark to the terminal
python3 scripts/gen_logo.py --banner --small
```

The generator is deterministic — a re-run with an unchanged sprite produces
byte-identical files, so a noisy diff means the art really did change.

## Palette

Six colours, NES-style discipline: one ink, one rim, one cast shadow, and a
three-step ramp for the burst.

| Char | Hex | Site token | Role |
| --- | --- | --- | --- |
| `l` | `#67E8F9` | `brand-300` | burst light — upper-left faces |
| `b` | `#22D3EE` | `brand-400` | burst base |
| `s` | `#0891B2` | `brand-600` | burst shade — lower-right faces |
| `d` | `#155E75` | `brand-800` | cast shadow, offset 1px down-right |
| `e` | `#1E293B` | slate-800 | tile rim, 1px |
| `k` | `#0F172A` | slate-900 | tile ink |

Every value is one the docs site already ships (`--color-brand-*` in
`lesysbot.github.io/src/styles/main.css`, and the slate the current favicon sits
on), so the mark and the site share one palette rather than two that nearly
match. Change a brand token there and this table is what needs to follow.

## Files

| File | Grid | Notes |
| --- | --- | --- |
| `lesysbot-mark.svg` | 32×32 | the primary mark |
| `lesysbot-mark-16.svg` | 16×16 | favicon cut |
| `lesysbot-mark-scanline.svg` | 32×32 | CRT variant, every other row one palette step darker |
| `lesysbot-wordmark.svg` | 152×32 | mark + `LESYSBOT` in the built-in 5×7 arcade caps |
| `lesysbot-mark-{16..1024}.png` | — | nearest-neighbour exports; no smoothing anywhere |
| `lesysbot-wordmark.png` | — | 8× export of the wordmark |
| `lesysbot.ico` | — | 16/32/64/128/256, each frame drawn at native scale |
| `banner.txt` | — | truecolor half-block banner, 16 rows — `install.{sh,ps1}` splash |
| `banner-small.txt` | — | the same in 8 rows — `uninstall.{sh,ps1}` splash |

**The 16px cut is redrawn, not scaled.** At that size the bevel and the cast
shadow turn to mud, so `MARK_16` is a separate sprite: two colours only — ink
and flat `brand-400` — with 2px arms and no shading at all. The ICO's 16px frame
uses it too — Pillow only reuses a supplied frame
on an exact size match, so every frame is built at its native scale and none get
resampled.

## Where these are used

| Copy | Lives at | Source file |
| --- | --- | --- |
| Repo header | this README, root `README.md` | `lesysbot-wordmark.svg` |
| Org profile header | `lesysbot/.github/profile/README.md` | same, via `raw.githubusercontent.com` |
| Docs site favicon | `lesysbot.github.io/src/assets/favicon.svg` | `lesysbot-mark.svg` |
| Docs site favicon (ICO) | `…/src/assets/favicon.ico` | `lesysbot.ico` |
| Docs site top bar + footer | `…/src/assets/logo.svg`, via `brandMark()` in `src/lib/layout.js` | `lesysbot-mark.svg` |
| Docs site home hero | `…/src/assets/wordmark.svg` | `lesysbot-wordmark.svg` |
| Apple touch icon | `…/src/assets/apple-touch-icon.png` | `lesysbot-mark-256.png` |
| Social preview | `…/src/assets/og-image.png` | `lesysbot-wordmark.png` |
| Status screen | `lesysbot` / `lesysbot manage` | drawn live — see below |
| Install splash | `scripts/install.sh` | `banner.txt` |
| Uninstall header | `scripts/uninstall.sh` | `banner-small.txt` |

**The site's copies are copies.** After regenerating, re-copy them:

```bash
cd lesysbot.github.io
B=../lesysbot/assets/brand
cp $B/lesysbot-mark.svg      src/assets/favicon.svg
cp $B/lesysbot-mark.svg      src/assets/logo.svg
cp $B/lesysbot.ico           src/assets/favicon.ico
cp $B/lesysbot-wordmark.svg  src/assets/wordmark.svg
cp $B/lesysbot-mark-256.png  src/assets/apple-touch-icon.png
cp $B/lesysbot-wordmark.png  src/assets/og-image.png
npm run build
```

The mark is referenced as an `<img>`, never inlined: it is ~1500 `<rect>`
elements, so inlining would add about 18 KB to every page twice over. The SVGs
carry `shape-rendering="crispEdges"`, so they stay sharp at any size with no
`image-rendering` needed on the page — and because the tile is dark ink, one
file serves both light and dark themes.

**The terminal mark is not read from `banner.txt`.** `lesysbot` (the status
screen) draws it live through `lesysbot/core/banner.py`, from the sprite copied
into `lesysbot/core/_logo.py` — that path goes through Rich, so the colour
downgrades by itself on 256- and 16-colour terminals and drops out entirely
under `NO_COLOR`, a dumb `TERM`, or a redirected stdout. `tests/test_banner.py`
decodes the rendered output back to the sprite, so the two copies cannot drift.

**The install and uninstall scripts do read the `.txt` files**, because they run
before there is any guarantee Python exists — `install.sh` prints the splash
above its own Python version check. Both gate on the same conditions the Python
path does (a TTY, no `NO_COLOR`, `TERM` isn't `dumb`, file present) and treat a
missing file as a no-op, so a partial checkout still installs. The shell reads
them with `sed`, never `printf`: the file is raw escape codes, which `printf`
would try to interpret as a format string.

Still unused: `lesysbot-mark-scanline.svg` and `lesysbot.ico`.

Assets live outside the `lesysbot/` package directory on purpose, so hatchling
never bundles them into the wheel.
