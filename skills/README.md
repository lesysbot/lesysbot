# LeSysBot skills for AI agents

This folder gives an AI agent everything it needs to **install, operate,
configure, and extend LeSysBot on a user's behalf** — without reading `docs/` or
the source code. Each subfolder is one skill in the standard Claude Skill
format: a `SKILL.md` with `name`/`description` frontmatter (used to decide
relevance) and self-contained, step-by-step instructions with exact commands.

**The folder is designed to be copied.** Drop it wherever your agent discovers
skills and it works standalone:

- **Claude Code** — copy the subfolders into a project's `.claude/skills/` or
  your global `~/.claude/skills/`.
- **Any other agent** — point it at this directory (or paste the relevant
  `SKILL.md`); every skill stands alone, and cross-references between skills
  are relative links inside this folder.

## Which skill handles what

| The user asks to… | Skill |
|---|---|
| "install lesysbot", "set it up on this machine" | [install-lesysbot](install-lesysbot/SKILL.md) |
| "update lesysbot", "upgrade to the latest version", "uninstall and update" | [update-lesysbot](update-lesysbot/SKILL.md) |
| "uninstall lesysbot", "remove it completely" | [uninstall-lesysbot](uninstall-lesysbot/SKILL.md) |
| "how do I use it", "run a tool", "why did it ask for confirmation" | [use-lesysbot](use-lesysbot/SKILL.md) |
| "change a setting", "edit the config", "increase history", "turn off logging" | [configure-lesysbot](configure-lesysbot/SKILL.md) |
| "change from ollama to vllm", "use OpenAI", "switch the model" | [switch-llm-backend](switch-llm-backend/SKILL.md) |
| "connect telegram", "set up slack", "message it from my phone" | [setup-messaging](setup-messaging/SKILL.md) |
| "install/disable/remove a tool", "list my tools" | [manage-tools](manage-tools/SKILL.md) |
| "restart the bot", "is it running", "start on boot", "show the logs" | [manage-service](manage-service/SKILL.md) |
| "monitor my system", "CPU/GPU/temperature graphs", "set up Grafana/Prometheus", "system dashboard" | [monitor-system](monitor-system/SKILL.md) |
| "it's broken", "not responding", "my tool doesn't show up" | [troubleshoot-lesysbot](troubleshoot-lesysbot/SKILL.md) |
| "write a tool", "make lesysbot able to X", "publish my tool" | [write-tool](write-tool/SKILL.md) |
| "fix a bug", "add an adapter", "run the tests", "contribute" | [develop-lesysbot](develop-lesysbot/SKILL.md) |

## Audiences

- **End users** (own a machine running LeSysBot): install-lesysbot,
  update-lesysbot, uninstall-lesysbot, use-lesysbot, configure-lesysbot,
  switch-llm-backend, setup-messaging, manage-tools, manage-service,
  monitor-system, troubleshoot-lesysbot.
- **Tool authors** (extend LeSysBot without touching its code): write-tool,
  plus manage-tools for the install/share round-trip.
- **Repo maintainers / contributors**: develop-lesysbot, plus
  troubleshoot-lesysbot for the isolated-verification recipe.

## Ground truth & maintenance

These skills are distilled from the repo's `docs/` and `CLAUDE.md` and are
intended to stay in sync with them: **when a behaviour change updates a doc
page, update the matching skill too** (the mapping mirrors the docs — e.g.
`docs/configuration.md` ↔ configure-lesysbot, `docs/service.md` ↔
manage-service, `monitoring/README.md` ↔ monitor-system). Where a skill and the
code disagree, the code is right — and the skill needs a fix.

Two facts worth knowing before any task:

- **`~/.lesysbot/` is the installed per-user home** (config, tools, logs;
  relocatable via `LESYSBOT_HOME`). Installed setups are edited there — never in
  the source checkout.
- **Slash commands and tool management work with no LLM running** — most
  verification needs no model at all.
