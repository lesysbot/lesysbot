# Write tools with Claude Code

LeSysBot ships a [Claude Code](https://code.claude.com/docs) plugin —
**`lesysbot-tool-dev`** — so an AI assistant can scaffold correct tool packages
for you in *any* repo: the core LeSysBot checkout, your own tools repo, or
a folder destined for `~/.lesysbot/tools/`. The plugin carries an `add-tool`
skill that encodes the package conventions (README frontmatter, `@tool` /
`CLITool`, typing, confirmation, requirement gating) so Claude gets them right
without you pasting docs into the chat.

This repo is also the plugin **marketplace**: the catalog lives in
[`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) and the
plugin itself in [`claude-plugin/lesysbot-tool-dev/`](../claude-plugin/lesysbot-tool-dev/).
Improve the skill here, push, and every installed copy can pull the update —
one source of truth, no per-repo drift.

## 1. The official packages repo — zero setup

The official package-collection repo
([lesysbot-packages-official](https://github.com/lesysbot/lesysbot-packages-official))
commits a `.claude/settings.json` that references this marketplace. Clone one,
open Claude Code inside it, and trust the folder when asked — Claude Code then
prompts you to install the `lesysbot` marketplace and enables `lesysbot-tool-dev`
automatically. After that, just ask: *"add a tool that checks whether a
systemd unit is running"*.

## 2. Manual install — any project

From any Claude Code session:

```
/plugin marketplace add lesysbot/lesysbot
/plugin install lesysbot-tool-dev@lesysbot
```

The skill is then available everywhere you run Claude Code, including an empty
folder where you're starting a brand-new tools repo.

## 3. Getting updates

```
/plugin marketplace update lesysbot
```

The plugin is deliberately **unversioned**, so every push to this repo counts
as a new version — updating the marketplace always gets you the current
conventions.

## 4. Recommend the plugin from your own tools repo

If you maintain a tools repo (see [Sharing Tools](sharing-tools.md)) and want
contributors to get the skill automatically, commit this as
`.claude/settings.json` in your repo:

```json
{
  "extraKnownMarketplaces": {
    "lesysbot": {
      "source": { "source": "github", "repo": "lesysbot/lesysbot" }
    }
  },
  "enabledPlugins": {
    "lesysbot-tool-dev@lesysbot": true
  }
}
```

Anyone who opens the repo in Claude Code and trusts it is offered the
marketplace, with the plugin enabled by default. (They can decline — it's a
prompt, not a silent install.)

## 5. How this relates to the other skill folders

Three skill locations exist, for three audiences — don't mix them up:

| Location | Audience | Purpose |
|---|---|---|
| `claude-plugin/lesysbot-tool-dev/` (this plugin) | Tool authors in **any** repo | Write tool packages |
| [`skills/`](../skills/README.md) | AI agents **operating** LeSysBot | Install, configure, manage a running bot |
| `.claude/skills/` | Contributors working **on this repo** | Core-repo specifics (bundled-tool catalog, tests) |

When tool-package conventions change, update the plugin's
[`add-tool` skill](../claude-plugin/lesysbot-tool-dev/skills/add-tool/SKILL.md)
**and** the core-repo project skill `.claude/skills/add-tool/` together —
they overlap by design.
