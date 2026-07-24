# Telegram & Slack

Where you talk to LeSysBot from. All three options behave identically once
you're chatting — same tools, same `/commands`, same confirmations, all covered
in [Everyday use](usage.md). Only the setup differs.

| Where | What you need | Best for |
|---|---|---|
| **[Terminal](#1-cli)** | nothing | Trying it out, local use, scripting |
| **[Telegram](#2-telegram)** | a bot token (2 minutes) | Reaching your machine from your phone |
| **[Slack](#3-slack)** | two app tokens (10 minutes) | A team or workspace |

Switch anytime with `--provider`, or by changing `messaging.provider` in your
config. The terminal always works regardless of what's configured.

---

## 1. CLI

The simplest adapter — no accounts, no tokens.

```bash
lesysbot --provider cli
```

- LLM responses **stream live and render as Markdown** (color, bold, headings, lists, code), with a `Thinking…` / `Running <tool>…` spinner while the model works.
- Slash-command and tool output is printed **verbatim**, so parameter signatures (`<host>`) and column layouts (e.g. `df`) are preserved.
- Confirmation prompts appear inline as `y/n` (the live display pauses so they stay readable).
- Background log lines stay out of the chat (they go to `logs/lesysbot.log`); use `-v` to show them.

| Input | What it does |
|---|---|
| Any text | Chat with the LLM |
| `/tool_name args` | Run a tool directly (no LLM) |
| `/help` · `/clear` · `/history` | Built-in commands |
| `exit` / `quit` / `q` | Leave the session |
| `Ctrl+C` | Force-exit |

👉 Full day-to-day usage (arguments, history, confirmations) is in **[Using LeSysBot](usage.md)**.

---

## 2. Telegram

Reach your bot from the Telegram app on any device.

### 2.1 Create your bot with BotFather

1. In Telegram, search for **[@BotFather](https://t.me/BotFather)** (the official bot, with a blue checkmark) and open a chat with it.
2. Send `/newbot`.
3. When prompted, enter a **display name** (e.g. `My LeSysBot`).
4. Then enter a **username** — it must be unique and **end in `bot`** (e.g. `my_lesysbot_bot`).
5. BotFather replies with your **bot token**, which looks like:

   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
   ```

   Keep this secret — anyone with it can control your bot.

### 2.2 Find your Telegram user ID

You'll use this to lock the bot to just you.

1. Search for **[@userinfobot](https://t.me/userinfobot)** in Telegram and press **Start**.
2. It immediately replies with your numeric **Id**, e.g. `123456789`.

*(Alternative: [@RawDataBot](https://t.me/RawDataBot) shows the same `id` field.)*

### 2.3 Configure

Put both values in `config.yaml`:

```yaml
messaging:
  provider: telegram
  telegram:
    token: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890"
    allowed_user_ids: [123456789]   # your ID — only you can use the bot
                                    # leave as [] to allow ANYONE who finds it
```

### 2.4 Run it

```bash
lesysbot --provider telegram
# (or just `lesysbot` if config.yaml already has provider: telegram)
```

Now open your bot in Telegram (search its username), press **Start**, and chat:

```
You:  what's the disk usage on /?
Bot:  The root filesystem has 143 GB free out of 980 GB (80% used).

You:  /ping 8.8.8.8
Bot:  PING 8.8.8.8 ... 3 packets transmitted, 3 received, 0% packet loss
```

Everything from [Using LeSysBot](usage.md) applies — natural language and `/commands` both work.

### 2.5 Restricting access

`allowed_user_ids` is an allow-list:

- `[123456789]` — only those user IDs can use the bot; everyone else gets `Unauthorized.`
- `[]` (empty) — **anyone** who finds your bot can use it (and run your tools). Only do this for a deliberately public bot.

Add more IDs as a comma-separated list: `[123456789, 987654321]`.

### 2.6 Confirmation prompts

Tools marked `confirm` show inline buttons before running:

```
⚠️ This will immediately reboot the machine. Proceed?
Tool: reboot_server

  [ ✅ Yes ]   [ ❌ No ]
```

Tap **✅ Yes** to approve or **❌ No** to cancel. If you don't respond within 120 seconds, the call is cancelled automatically.

### 2.7 Troubleshooting

| Symptom | Fix |
|---|---|
| Bot replies `Unauthorized.` | Your user ID isn't in `allowed_user_ids`. Re-check it via [@userinfobot](https://t.me/userinfobot). |
| No response at all | Wrong token, or LeSysBot isn't running. Check the logs; confirm `lesysbot --provider telegram` is up. |
| Replies look like raw `*markdown*` | Harmless — the model emitted Markdown Telegram couldn't format, so it was sent as plain text. |

---

## 3. Slack

Run LeSysBot as a Slack app you message directly. Slack needs **two** tokens — a
**bot token** (`xoxb-…`) and an **app-level token** (`xapp-…`) — and uses Socket
Mode so you don't need a public URL.

> **Dependency:** the Slack adapter is the `slack` extra. The install scripts
> include it; after a bare `pip install .` add it with `pip install ".[slack]"`.

### 3.1 Create the Slack app from a manifest

The manifest sets all the scopes and settings in one step.

1. Go to **[api.slack.com/apps](https://api.slack.com/apps)** → **Create New App** → **From a manifest**.
2. Choose the workspace to install into, then click **Next**.
3. Switch the format to **YAML** and paste this manifest:

   ```yaml
   display_information:
     name: LeSysBot
   features:
     bot_user:
       display_name: LeSysBot
       always_online: true
   oauth_config:
     scopes:
       bot:
         - chat:write       # send messages
         - im:history       # read direct messages sent to the bot
         - im:read          # basic info about DM channels
         - im:write         # open a DM with a user
   settings:
     event_subscriptions:
       bot_events:
         - message.im       # receive direct messages
     socket_mode_enabled: true
   ```

4. Click **Next** → **Create**.

### 3.2 Generate the app-level token (`xapp-…`)

1. In your app's settings, open **Basic Information**.
2. Scroll to **App-Level Tokens** → **Generate Token and Scopes**.
3. Name it (e.g. `socket`), add the **`connections:write`** scope, and click **Generate**.
4. Copy the token — it starts with **`xapp-`**. This is your `app_token`.

### 3.3 Install the app and get the bot token (`xoxb-…`)

1. Open **Install App** (or **OAuth & Permissions**) → **Install to Workspace** → **Allow**.
2. Copy the **Bot User OAuth Token** — it starts with **`xoxb-`**. This is your `bot_token`.

### 3.4 Find your Slack member ID

Useful to know who you are in Slack (and for any per-user logic):

1. In Slack, click your **profile picture** → **Profile**.
2. Click the **⋮ (More)** button → **Copy member ID**.
3. It looks like `U01ABC2DEF`.

### 3.5 Configure

```yaml
messaging:
  provider: slack
  slack:
    bot_token: "xoxb-your-bot-token"
    app_token: "xapp-your-app-token"
```

### 3.6 Run it and message the bot

```bash
lesysbot --provider slack
# (or just `lesysbot` if config.yaml already has provider: slack)
```

In Slack, find **LeSysBot** under **Apps** in the sidebar (or search its name), open a
direct message, and chat:

```
You:  what's the disk usage on /?
LeSysBot:  The root filesystem has 143 GB free out of 980 GB (80% used).

You:  /ping 8.8.8.8
LeSysBot:  PING 8.8.8.8 ... 0% packet loss
```

### 3.7 Notes & limitations

- **Access:** the app is limited to your Slack workspace — anyone in the workspace who can DM the app can use it. Unlike Telegram, the Slack adapter has no per-user allow-list in config; restrict the app at the workspace level if needed.
- **Direct tool calls:** Slack treats a leading `/` as its own slash-command system. To call a LeSysBot tool directly, type `/ ` **with a space** first: `/ disk_usage path=/tmp`. (Natural-language chat needs no prefix.)
- **Confirmation prompts auto-approve** in Slack by default. To add ✅/❌ buttons, override `SlackAdapter.confirm()` with Slack Block Kit — see [§4](#4-building-a-custom-adapter).

### 3.8 Troubleshooting

| Symptom | Fix |
|---|---|
| "The 'slack' provider needs a dependency that isn't installed" | `pip install ".[slack]"` — it bundles `slack-bolt` and `aiohttp`. |
| `not_authed` / `invalid_auth` | A token is wrong or swapped. `bot_token` is `xoxb-…`, `app_token` is `xapp-…`. |
| Bot never responds to DMs | Make sure Socket Mode is on, the app is installed, and the manifest's `message.im` event + `im:history` scope are present. Reinstall the app after scope changes. |
| Can't find the bot to DM | Look under **Apps** in the Slack sidebar, or invite it to a channel and DM from its profile. |

---

## 4. Building a custom adapter

To support another platform, subclass `MessagingAdapter`
(`lesysbot/messaging/base.py`) and implement `start()` and `send()`. Override
`confirm()` to add a confirmation UI (the default auto-approves).

```python
# lesysbot/messaging/myplatform.py
from typing import Any
from lesysbot.messaging.base import MessageHandler, MessagingAdapter

class MyPlatformAdapter(MessagingAdapter):

    async def start(self, handler: MessageHandler) -> None:
        """Connect to the platform and call handler(user_id, text) for each message."""
        async for user_id, text in my_platform.listen():
            reply = await handler(user_id, text)
            await self.send(user_id, reply)

    async def send(self, user_id: str, text: str) -> None:
        """Send a reply to the user."""
        await my_platform.send_message(user_id, text)

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        """Show a confirmation UI before a confirm=True tool runs.
        Return True to approve, False to cancel. Default auto-approves."""
        return await my_platform.ask_yes_no(user_id, prompt)
```

Wire it into the `if/elif` block in `lesysbot/__main__.py`:

```python
elif provider == "myplatform":
    from lesysbot.messaging.myplatform import MyPlatformAdapter
    adapter = MyPlatformAdapter(settings.messaging.myplatform)
```

and make sure `agent.set_confirm_fn(adapter.confirm)` is called so your
confirmation UI is used. For how the adapter fits into the rest of the system
see [Architecture](architecture.md); to submit your adapter as a pull request,
follow [CONTRIBUTING.md §5](../CONTRIBUTING.md#5-contributing-a-messaging-adapter).
