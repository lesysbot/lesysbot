---
name: setup-messaging
description: Connect LeSysBot to Telegram or Discord (tokens, access control, running it), or switch back to terminal-only — including the boot-time startup notice. Use when asked to "set up telegram", "connect discord", "message the bot from my phone", "restrict who can use the bot", or "configure the startup notification".
---

# Set up Telegram / Discord messaging

The adapter is chosen by `messaging.provider` (`cli | telegram | discord`) or the
`--provider` flag. Telegram/Discord normally run as a **background service**
(Telegram polls, Discord holds a gateway websocket); the terminal stays available
regardless via `lesysbot --provider cli`. Easiest end-to-end path: re-run the
install wizard and pick the provider — it writes the config *and*
installs/replaces the service. The sections below are the manual route.

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

## 2. Discord

One bot token, no public URL. The adapter is the `discord` extra (`discord.py`);
the install scripts include it, otherwise `pip install ".[discord]"`.

**Create the bot:** [discord.com/developers/applications](https://discord.com/developers/applications)
→ New Application → name it → **Bot** tab.

**Enable the Message Content intent — this is the step everyone misses.** Bot →
Privileged Gateway Intents → **MESSAGE CONTENT INTENT** on → Save. Without it the
gateway delivers every message with empty `content`, so the bot connects, shows
as online, and silently ignores everything.

**Bot token:** Bot → **Reset Token** → copy it (shown once), e.g.
`MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl.mNoPqRs…`.

**Invite it to a server** (required before it can be DM'd): OAuth2 → URL
Generator → scopes **`bot`** *and* **`applications.commands`** (the second is what
makes tools appear in the `/` picker) → permissions **View Channels**,
**Send Messages**, **Read Message History** → open the URL and pick a server.

**Get your numeric user ID:** Settings → Advanced → **Developer Mode** on, then
right-click your name → **Copy User ID** (18–19 digits). Same right-click gives
**Copy Channel ID** for a channel.

**Configure and run:**

```yaml
messaging:
  provider: discord
  discord:
    token: "MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl.mNoPqRs..."
    allowed_user_ids: [123456789012345678]   # allow-list; [] = anyone sharing a server
```

`lesysbot --provider discord` (or just `lesysbot` with the config above). DM the
bot, or **@-mention** it in a channel.

- **DMs:** every message is handled. **Channels:** only messages that @-mention
  the bot — otherwise it would answer everything in every channel it can see.
  The mention is stripped before the text reaches the model.
- Access control: users not in `allowed_user_ids` get `Unauthorized.` — an empty
  list allows anyone who shares a server with the bot, and logs a warning at
  startup. This matters more than on Telegram: sharing a server is enough to DM.
- Confirm-gated tools show ✅ Yes / ❌ No buttons; no answer in 300 s cancels. In
  a channel only the requester can click; others get an ephemeral refusal.
- Every tool is also registered as a **native application command**, so `/` opens
  a picker with a typed field per parameter. Needs the `applications.commands`
  scope on the invite; the set is synced at startup, so a tool added later joins
  the picker after a restart (callable as typed text immediately).
- `Discord rejected the bot token` → wrong/revoked token, reset it. Online but
  deaf → Message Content intent. Can't DM it → not in a shared server yet.

## 3. Startup notice (Telegram/Discord only)

When the bot comes up it sends a short system report — CPU/GPU temperature,
disk usage, internet speed, uptime; lines the host can't answer are omitted.
Since a service starts at boot, this doubles as a "machine just booted" ping.

```yaml
messaging:
  startup_notice:
    enabled: true        # false to turn off
    notify: []           # Telegram chat ids / Discord user or channel ids
                         # falls back to that provider's allowed_user_ids when
                         # empty, so usually nothing to set here
    speedtest: true      # false to skip (downloads speedtest_mb MB each boot)
    speedtest_mb: 5
```

## 4. Back to terminal-only

Set `provider: cli` (or re-run the wizard and pick Terminal) and restart the
service. It keeps running — it still serves the control panel — but stops polling
Telegram/Discord; chat with `lesysbot --provider cli`. See
[manage-service](../manage-service/SKILL.md).

## Related

- Install/replace the background service: [manage-service](../manage-service/SKILL.md).
- All keys: [configure-lesysbot](../configure-lesysbot/SKILL.md).
