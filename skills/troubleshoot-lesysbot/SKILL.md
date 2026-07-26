---
name: troubleshoot-lesysbot
description: Diagnose and fix LeSysBot problems — LLM unreachable, tools missing from /help, edits that seem to do nothing (stale-install shadowing), service crashes, messaging auth errors — plus where every log lives and how to test in an isolated scratch environment. Use when something is "broken", "not responding", "not showing up", or behaving differently than expected.
---

# Troubleshoot LeSysBot

## First: where the evidence lives

```bash
tail -f ~/.lesysbot/logs/lesysbot.log      # application log (INFO+; imports, hot reload, errors)
tail -f ~/.lesysbot/logs/traces.jsonl    # one JSON line per request: tools called, args, timings
journalctl --user -u lesysbot -f         # Linux service stdout/stderr
```

(For a dev checkout with a local `./config.yaml`, logs are in the repo's
`logs/` instead.) The interactive CLI console only shows WARNING+ — evidence
of tool loads/reloads is in the **file**, not on screen; `-v` puts DEBUG on
screen. `lesysbot tools list` shows per-tool availability, and
`lesysbot tools info NAME` explains why a specific tool can't run here.

## The #1 developer trap: stale-install shadowing

A **non-editable** `pip install` (e.g. from the install wizard) shadows a
development clone: the `lesysbot` command runs the old site-packages copy, so
code edits, new tools, new flags "do nothing" — `/help` may even show no tools.

```bash
python -c "import lesysbot; print(lesysbot.__file__)"   # run from OUTSIDE the repo
pip install -e .                                    # fix: must point at the clone after
```

Suspect this whenever behaviour doesn't match the code you're looking at.

## Symptom → fix

| Symptom | Cause & fix |
|---|---|
| `LLM unavailable: …` | Backend unreachable. `curl http://localhost:11434/` (Ollama) — start it, or fix `llm.base_url`. Slash commands still work with no model. |
| `model "x" not found` | `ollama pull x`, or fix `llm.model` to a name from `ollama list`. |
| Wrong tool picked / no tool used | Small models call tools unreliably — switch to Qwen3.5/Gemma4, or run the tool directly with `/`. |
| First reply very slow | Model loading into memory on first use; later replies are faster. |
| Tool missing from `/help` | File not in the tools dir, name starts with `_`, or an import error — check `lesysbot.log`. Also consider stale-install shadowing (above) and *which* tools dir is active (installed setup = `~/.lesysbot/tools/`, dev checkout = repo `tools/`). |
| Tool listed but "⚠ unavailable here" | Deliberate gating: wrong OS for its `platforms`, or a `requires` binary not on PATH. Install the binary or run on a supported OS. |
| `/tool` returns "disabled" | It was disabled — `lesysbot tools enable NAME`. It applies live (the bot watches `tool_state.json`). |
| `lesysbot: command not found` | pip's script dir not on PATH: `python -m site --user-scripts`, add it (Windows: Python `Scripts\` dir). |
| Service exits immediately | Read `journalctl --user -u lesysbot` — usually Ollama down, wrong `WorkingDirectory` (must hold `config.yaml`/`tools/`), or bad Telegram/Discord tokens. |
| Control panel unreachable (`lesysbot` shows it offline) | The service isn't running — start it (see [manage-service](../manage-service/SKILL.md)); or serve it ad-hoc with `lesysbot manage`. |
| Log: `Control panel not started — port … already in use` | Something else owns `webui.port` (often a second LeSysBot). Change the port and restart; the bot itself keeps running. |
| Telegram: `Unauthorized.` | Your ID isn't in `allowed_user_ids` — re-check via @userinfobot. |
| Telegram: no response at all | Wrong token or the bot isn't running. |
| Telegram: raw `*markdown*` in replies | Harmless fallback — unformattable Markdown is sent as plain text. |
| "The 'discord' provider needs a dependency that isn't installed" | `pip install ".[discord]"`. |
| Discord: connects but ignores everything | MESSAGE CONTENT INTENT is off — enable it under Bot → Privileged Gateway Intents, restart. |
| Discord: `Discord rejected the bot token` | Wrong/revoked token — Bot → Reset Token, update config. |
| Discord: silent in channels | Channel messages must **@-mention** the bot; DMs need no mention. |
| Tool missing from the `/` menu | Menu is built at startup — restart. Discord also needs the `applications.commands` invite scope. Disabled/unavailable tools are excluded by design. |
| A tool never shows in the `/` menu | Name must be `[a-z0-9_]` (both platforms' rule) — see the startup warning. Still callable as typed text. |
| Config edits don't apply | Wrong file — check the search order (`-c` flag → `./config.yaml` → `~/.lesysbot/config.yaml` → …) and that the service was restarted. Env vars/flags override the file. |
| Install: `tools dir already has X` | Folder not created by the installer — `--force` to overwrite. |
| Changed settings, old bot still polling | A leftover service from a previous install — stop/remove it (see [manage-service](../manage-service/SKILL.md)). |
| "Another LeSysBot instance … is already running (PID N)" | The single-instance guard: that bot is already up, usually as the service. Stop it for a foreground run, or use `lesysbot --provider cli` (no conflict). |
| Telegram: `409 Conflict` getUpdates spam | Two processes polling the same token — one predates the single-instance guard, or runs on another machine. Keep exactly one; the guard blocks a second copy per machine. |

## Testing safely in an isolated scratch environment

Never experiment against a live `~/.lesysbot` (a real service may be using it).
All paths anchor to the cwd when no config is found, and `LESYSBOT_HOME`
redirects the `~/.lesysbot` fallback:

```bash
S=$(mktemp -d) && mkdir -p "$S/tools" "$S/home"
cd "$S" && export LESYSBOT_HOME="$S/home"
# state now lands in $S: tool_state.json, tools.lock.json, logs/
```

- `lesysbot tools …` just works from `$S`; `echo n | lesysbot tools remove X`
  exercises the abort path, `-y` skips confirmation.
- The CLI adapter exits on stdin EOF — for a background bot hold stdin open:

```bash
(tail -f /dev/null | lesysbot --provider cli > "$S/bot.log" 2>&1 &)
echo $! > "$S/bot.pid"
sleep 5 && grep -i "tools loaded" "$S/bot.log"
```

- No LLM is needed for slash commands or tool management.
- Kill by the PID you recorded, not `pkill -f` with the launch string: that
  pattern also matches the shell command that started it, and kills your own
  shell (exit 144).

## Related

- Every log/level/rotation setting: [configure-lesysbot](../configure-lesysbot/SKILL.md).
- Backend health & model choice: [switch-llm-backend](../switch-llm-backend/SKILL.md).
- Service internals: [manage-service](../manage-service/SKILL.md).
