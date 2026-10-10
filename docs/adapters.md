# Telegram & Discord

Chat with your machine from your phone. You need two things from the chat app —
a **bot token** and **your user ID** — then give them to `lesysbot setup`.

Everything in [Everyday use](usage.md) works the same here.

## Telegram

**1. Create the bot.** In Telegram, open [@BotFather](https://t.me/BotFather),
send `/newbot`, and pick a name and a username ending in `bot`. BotFather replies
with a token like `1234567890:ABCdef…`. Keep it secret.

**2. Find your user ID.** Open [@userinfobot](https://t.me/userinfobot) and
press **Start**. It replies with a number like `123456789`.

**3. Connect LeSysBot.**

```bash
lesysbot setup
```

Answer **y** to replace your settings, choose **Telegram**, then paste the
token and your ID. The service restarts and the bot messages you when it's
online.

**4. Chat.** Search for your bot's username in Telegram and press **Start**.

## Discord

**1. Create the bot.** Go to the
[Discord developer portal](https://discord.com/developers/applications) →
**New Application** → open the **Bot** tab.

**2. Turn on Message Content.** On the **Bot** tab, enable **Message Content
Intent** and save. Without it the bot comes online but ignores you.

**3. Copy the token.** Click **Reset Token** and copy it. Discord shows it once.

**4. Invite it to a server.** Open **OAuth2 → URL Generator**. Tick the scopes
**`bot`** and **`applications.commands`**, and the permissions **View
Channels**, **Send Messages** and **Read Message History**. Open the generated
link and pick your server.

**5. Find your user ID.** In Discord, go to **Settings → Advanced** and turn on
**Developer Mode**. Then right-click your name → **Copy User ID**.

**6. Connect LeSysBot.**

```bash
lesysbot setup
```

Answer **y** to replace your settings, choose **Discord**, then paste the
token and your ID.

**7. Chat.** Send the bot a direct message, or @-mention it in a channel. In
channels it only answers when mentioned.

## Who can use the bot

Only the user IDs you entered. Anyone else gets `Unauthorized.`

To add someone, edit `~/.lesysbot/config.yaml` and restart the service:

```yaml
messaging:
  provider: telegram          # or discord
  telegram:
    token: "1234567890:ABCdef…"
    allowed_user_ids: [123456789, 987654321]
```

> ⚠️ An empty list, `[]`, lets **anyone** who finds the bot run your tools —
> including powering off the machine. See [Security](security.md).

## Good to know

- **Confirmations** arrive as ✅ / ❌ buttons. They expire after 2 minutes on
  Telegram and 5 on Discord.
- **The `/` menu** lists every tool. A tool you install later works when typed,
  and joins the menu after the next restart.
- **A startup message** tells you when the bot comes online — useful as a "the
  machine just rebooted" ping. Turn it off with
  `messaging.startup_notice.enabled: false`.
- **The terminal still works.** `lesysbot chat` runs alongside the service.

Not working? See [Troubleshooting](troubleshooting.md#telegram-and-discord).
