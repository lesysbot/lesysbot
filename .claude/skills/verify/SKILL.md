---
name: verify
description: How to run and drive LeSysBot end-to-end in an isolated scratch environment — the interactive CLI and the `lesysbot` management subcommands — without touching the user's real ~/.lesysbot or the installed Telegram service.
---

# Verifying LeSysBot changes

## Gotcha first: stale-install shadowing

A plain `pip install .` is **non-editable**,
which shadows this repo for any run outside the repo directory (`lesysbot` then
uses the old site-packages copy — new subcommands/flags "don't exist").
Always check and fix before verifying:

```bash
python3 -c "import lesysbot; print(lesysbot.__file__)"   # run from OUTSIDE the repo
pip install -e .                                      # must point at this repo after
```

## Isolated environment

Never drive `~/.lesysbot` — a real Telegram service may be running from it.
All paths anchor to the cwd when no config file is found, and `LESYSBOT_HOME`
redirects the `~/.lesysbot` fallback:

```bash
S=$(mktemp -d)                      # scratch root
mkdir -p "$S/tools/mypkg" "$S/home"
# write tool packages under $S/tools/…, optionally a lock: $S/tools.lock.json
cd "$S" && export LESYSBOT_HOME="$S/home"
```

State then lands in `$S/tool_state.json`, `$S/tools.lock.json`, `$S/logs/`.

## Driving the surfaces

**Subcommand CLI** (`lesysbot install|list|enable|remove|…`) — just run it from `$S`.
The y/N confirmation reads stdin, so `echo n | lesysbot remove X` exercises
the abort path and `-y` skips it.

**Interactive bot** — the CLI adapter exits on stdin EOF, so hold stdin open
with `tail -f /dev/null |`. Write the PID to a file rather than finding it later
with `pgrep -f`, whose pattern also matches *your own* shell (see Cleanup):

```bash
cat > "$S/run-bot.sh" <<'SH'
#!/bin/bash
cd "$(dirname "$0")"
export LESYSBOT_HOME="$PWD/home"
tail -f /dev/null | lesysbot --provider cli > "$1" 2>&1 &
echo $! > bot.pid
SH
chmod +x "$S/run-bot.sh" && "$S/run-bot.sh" "$S/bot.log" && sleep 5
grep -i "tools loaded" "$S/bot.log"
```

To drive slash commands instead of holding the session open, pipe them in:
`printf '/help\n/temperature\nexit\n' | lesysbot --provider cli`. Config values can
be overridden from the environment with the `LESYSBOT_<SECTION>__<FIELD>`
pattern (e.g. `LESYSBOT_MCP__HOT_RELOAD=false`).

No LLM is needed for slash commands or tool management — only free-form chat
turns call the backend, so a run with Ollama down still exercises both.

Hot-reload evidence (tool loads/removals/reloads) is in `$S/logs/lesysbot.log`
(INFO level) — the interactive console clamps to WARNING, so don't look there.

**Cleanup:** `kill $(cat "$S/bot.pid")`. Never `pkill -f`/`pgrep -f` with the
launch string: if the same command line also *launched* the bot earlier in your
shell command, the pattern matches your own shell and kills it (exit 144). The
`[i]` bracket trick does not save you — it only stops the pattern matching
itself, not the launch command sitting in the same argv.
