---
name: setup-messaging
description: Connect LeSysBot to Telegram or Slack (tokens, access control, running it), or switch back to terminal-only — including the boot-time startup notice. Use when asked to "set up telegram", "connect slack", "message the bot from my phone", "restrict who can use the bot", or "configure the startup notification".
---

# Set up Telegram / Slack messaging

The adapter is chosen by `messaging.provider` (`cli | telegram | slack`) or the
`--provider` flag. Telegram/Slack normally run as a **background service** (they
poll for messages); the terminal stays available regardless via
`lesysbot --provider cli`. Easiest end-to-end path: re-run the install wizard and
pick the provider — it writes the config *and* installs/replaces the service.
The sections below are the manual route.

## 1. Telegram

**Get a bot token:** message [@BotFather](https://t.me/BotFather) → `/newbot` →
pick a display name, then a unique username ending in `bot` → it replies with a
token like `1234567890:ABCdef…`. Keep it secret.

**Get your numeric user ID:** message [@userinfobot](https://t.me/userinfobot)
→ it replies with your `Id`, e.g. `123456789`.

**Configure** (`~/.lesysbot/config.yaml` for an installed setup):

```yaml
messaging:
  provider: telegram
  telegram:
    token: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890"
    allowed_user_ids: [123456789]   # allow-list; [] = ANYONE who finds the bot
```

**Run:** `lesysbot --provider telegram` (or just `lesysbot` with the config above);
restart the service if one is installed. Open the bot in Telegram, press
**Start**, chat. Natural language and `/commands` both work.

- Access control: users not in `allowed_user_ids` get `Unauthorized.` — an
  empty list allows everyone, only acceptable for a deliberately public bot.
- Confirm-gated tools show ✅ Yes / ❌ No buttons; no answer in 120 s cancels.
- Replies showing raw `*markdown*` are harmless — malformed Markdown falls
  back to plain text rather than dropping the message.

## 2. Slack

Slack needs **two tokens** and Socket Mode (no public URL). The adapter is
the `slack` extra (`slack-bolt` + `aiohttp`); the install scripts include it,
otherwise `pip install ".[slack]"`.

**Create the app from a manifest:** [api.slack.com/apps](https://api.slack.com/apps)
→ Create New App → *From a manifest* → pick the workspace → YAML:

```yaml
display_information:
  name: LeSysBot
features:
  bot_user:
    display_name: LeSysBot
    always_online: true
oauth_config:
  scopes:
    bot: [chat:write, im:history, im:read, im:write]
settings:
  event_subscriptions:
    bot_events: [message.im]
  socket_mode_enabled: true
```

**App-level token (`xapp-…`):** Basic Information → App-Level Tokens →
Generate, with scope **`connections:write`**.

**Bot token (`xoxb-…`):** Install App → Install to Workspace → Allow → copy
the Bot User OAuth Token.

**Configure and run:**

```yaml
messaging:
  provider: slack
  slack:
    bot_token: "xoxb-..."
    app_token: "xapp-..."
```

DM the app from the **Apps** section of the Slack sidebar.

- **No per-user allow-list** — anyone in the workspace who can DM the app can
  use it; restrict at the workspace level.
- **Direct tool calls need `/ ` with a space** (`/ disk_usage path=/tmp`) —
  a bare `/` is claimed by Slack's own slash-command system.
- Confirm-gated tools **auto-approve** in Slack by default.
- `not_authed` / `invalid_auth` → tokens wrong or swapped (`xoxb` = bot,
  `xapp` = app). No response to DMs → check Socket Mode is on and reinstall
  the app after any scope change.

## 3. Startup notice (Telegram/Slack only)

When the bot comes up it sends a short system report — CPU/GPU temperature,
disk usage, internet speed, uptime; lines the host can't answer are omitted.
Since a service starts at boot, this doubles as a "machine just booted" ping.

```yaml
messaging:
  startup_notice:
    enabled: true        # false to turn off
    notify: []           # Telegram chat ids / Slack channel ids
                         # Telegram falls back to allowed_user_ids when empty;
                         # Slack sends nothing unless a channel id is set here
    speedtest: true      # false to skip (downloads speedtest_mb MB each boot)
    speedtest_mb: 5
```

## 4. Back to terminal-only

Set `provider: cli` (or re-run the wizard and pick Terminal) and restart the
service. It keeps running — it still serves the management panel — but stops polling
Telegram/Slack; chat with `lesysbot --provider cli`. See
[manage-service](../manage-service/SKILL.md).

## Related

- Install/replace the background service: [manage-service](../manage-service/SKILL.md).
- All keys: [configure-lesysbot](../configure-lesysbot/SKILL.md).
