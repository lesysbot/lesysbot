# Telegram & Discord

Where you talk to LeSysBot from. All three options behave identically once
you're chatting — same tools, same `/commands`, same confirmations, all covered
in [Everyday use](usage.md). Only the setup differs.

| Where | What you need | Best for |
|---|---|---|
| **[Terminal](#1-cli)** | nothing | Trying it out, local use, scripting |
| **[Telegram](#2-telegram)** | a bot token (2 minutes) | Reaching your machine from your phone |
| **[Discord](#3-discord)** | a bot token (5 minutes) | A server you already live in |

Switch anytime with `--provider`, or by changing `messaging.provider` in your
config. The terminal always works regardless of what's configured.

---

## 1. CLI

The simplest adapter — no accounts, no tokens.

```bash
lesysbot chat
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
lesysbot run
# (or `lesysbot --provider telegram` to override what config.yaml says)
```

Now open your bot in Telegram (search its username), press **Start**, and chat:

```
You:  what's the disk usage on /?
Bot:  The root filesystem has 143 GB free out of 980 GB (80% used).

You:  /ping 8.8.8.8
Bot:  PING 8.8.8.8 ... 3 packets transmitted, 3 received, 0% packet loss
```

Everything from [Using LeSysBot](usage.md) applies — natural language and `/commands` both work.

### 2.5 The command menu

LeSysBot publishes its tools to Telegram's command list at startup, so typing
`/` shows every tool with its description instead of you having to remember
names. Telegram has no typed parameters, so arguments stay free text
(`/disk_usage path=/tmp`).

The menu is registered once per start: a newly installed tool is callable
immediately but appears in the menu after a restart. In group chats Telegram
appends the bot's username to a command (`/disk_usage@my_bot`) — that's handled,
so group and direct chats behave the same.

### 2.6 Restricting access

`allowed_user_ids` is an allow-list:

- `[123456789]` — only those user IDs can use the bot; everyone else gets `Unauthorized.`
- `[]` (empty) — **anyone** who finds your bot can use it (and run your tools). Only do this for a deliberately public bot.

Add more IDs as a comma-separated list: `[123456789, 987654321]`.

### 2.7 Confirmation prompts

Tools marked `confirm` show inline buttons before running:

```
⚠️ This will immediately reboot the machine. Proceed?
Tool: reboot_server

  [ ✅ Yes ]   [ ❌ No ]
```

Tap **✅ Yes** to approve or **❌ No** to cancel. If you don't respond within 120 seconds, the call is cancelled automatically.

### 2.8 Troubleshooting

| Symptom | Fix |
|---|---|
| Bot replies `Unauthorized.` | Your user ID isn't in `allowed_user_ids`. Re-check it via [@userinfobot](https://t.me/userinfobot). |
| No response at all | Wrong token, or LeSysBot isn't running. Check the logs; confirm `lesysbot --provider telegram` is up. |
| Replies look like raw `*markdown*` | Harmless — the model emitted Markdown Telegram couldn't format, so it was sent as plain text. |

---

## 3. Discord

Run LeSysBot as a Discord bot you DM, or @-mention in a server channel. One bot
token, no public URL.

> **Dependency:** the Discord adapter is the `discord` extra. The install scripts
> include it; after a bare `pip install .` add it with `pip install ".[discord]"`.

### 3.1 Create the application and its bot

1. Go to **[discord.com/developers/applications](https://discord.com/developers/applications)** → **New Application**.
2. Name it (e.g. `LeSysBot`), accept the terms, and click **Create**.
3. Open the **Bot** tab in the left sidebar.

### 3.2 Turn on the Message Content intent

**Do not skip this.** Without it Discord delivers every message with its text
stripped out, so the bot connects, looks online, and silently ignores you.

1. On the **Bot** tab, scroll to **Privileged Gateway Intents**.
2. Enable **MESSAGE CONTENT INTENT** and save.

### 3.3 Copy the bot token

1. Still on the **Bot** tab, click **Reset Token** → **Yes, do it**.
2. Copy the token that appears. It looks like:

   ```
   MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl.mNoPqRs…
   ```

   Discord shows it **once** — copy it now. Keep it secret: anyone with it can
   control your bot. (Lost it? Reset it again; the old one stops working.)

### 3.4 Invite the bot to a server

A bot can't DM you until you share a server with it.

1. Open **OAuth2** → **URL Generator**.
2. Under **Scopes**, tick **`bot`** *and* **`applications.commands`** — the second
   one is what lets the tools appear in the server's `/` picker ([§3.8](#38-running-tools-from-the-command-picker)).
3. Under **Bot Permissions**, tick **View Channels**, **Send Messages** and **Read Message History**.
4. Copy the generated URL at the bottom, open it in a browser, and pick a server you own.

### 3.5 Find your Discord user ID

You'll use this to lock the bot to just you.

1. In Discord, open **Settings** (the ⚙ by your name) → **Advanced** → turn on **Developer Mode**.
2. Right-click your own name anywhere → **Copy User ID**.
3. It's an 18–19 digit number, e.g. `123456789012345678`.

*(The same right-click → **Copy Channel ID** works on a channel, which is what
you'd put in `startup_notice.notify` to have the boot report land in a channel.)*

### 3.6 Configure

```yaml
messaging:
  provider: discord
  discord:
    token: "MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl.mNoPqRs..."
    allowed_user_ids: [123456789012345678]   # your ID — only you can use the bot
                                             # leave as [] to allow anyone who
                                             # shares a server with the bot
```

### 3.7 Run it and message the bot

```bash
lesysbot run
# (or `lesysbot --provider discord` to override what config.yaml says)
```

The bot appears online in your server's member list. **DM it**, or **@-mention it**
in a channel:

```
You:  what's the disk usage on /?
LeSysBot:  The root filesystem has 143 GB free out of 980 GB (80% used).

You:  /ping 8.8.8.8
LeSysBot:  PING 8.8.8.8 ... 3 packets transmitted, 3 received, 0% packet loss
```

In a **DM** every message is for the bot. In a **server channel** it only answers
when @-mentioned — otherwise it would reply to everything said in every channel
it can see. The mention is stripped before the text reaches the model, so
`@LeSysBot how much RAM is free?` asks exactly what you typed.

Everything from [Using LeSysBot](usage.md) applies — natural language and
`/commands` both work.

### 3.8 Running tools from the command picker

Every tool is registered as a Discord **application command**, so you don't have
to remember names or argument syntax. Type `/` and Discord lists the tools; pick
one and it gives you a labelled field per parameter:

```
/disk_usage
   path      ← required, described, text field
   depth     ← optional, numbers only
```

Discord marks required fields, refuses letters in a number field, and shows each
parameter's description. The model is not involved — this is the same direct tool
call as typing `/disk_usage path=/`, which also still works.

Notes:

- **The picker is filled in when the bot starts.** A newly installed tool (or one
  you just re-enabled) is callable as text immediately but joins the picker after
  a restart — Discord rate-limits command updates, so LeSysBot registers once
  instead of on every change to your tools folder.
- Disabled tools and tools unavailable on this machine are left out.
- Confirm-gated tools still ask first — the ✅/❌ prompt appears in the channel you
  ran the command in, and the result follows once you answer.
- A tool whose name isn't valid as a command (Discord and Telegram allow only
  lowercase letters, digits and `_`) is skipped with a warning in the log; it
  stays callable as typed text.

### 3.9 Restricting access

`allowed_user_ids` is an allow-list, and it matters more here than on Telegram:
anyone who shares a server with your bot can open a DM with it.

- `[123456789012345678]` — only those user IDs can use the bot; everyone else gets `Unauthorized.`
- `[]` (empty) — **anyone** who shares a server with the bot can use it (and run your tools). LeSysBot logs a warning at startup when the list is empty.

Add more IDs as a comma-separated list: `[123456789012345678, 987654321098765432]`.

### 3.10 Confirmation prompts

Tools marked `confirm` show buttons before running:

```
⚠️ This will immediately reboot the machine. Proceed?
Tool: reboot_server

  [ ✅ Yes ]   [ ❌ No ]
```

Click **✅ Yes** to approve or **❌ No** to cancel; the message updates to show
which you picked. In a channel, only the person who made the request can answer
— anyone else clicking gets a private "not yours to answer" note. If nobody
responds within five minutes, the call is cancelled.

### 3.11 Troubleshooting

| Symptom | Fix |
|---|---|
| "The 'discord' provider needs a dependency that isn't installed" | `pip install ".[discord]"`. |
| Bot is online but ignores everything | **MESSAGE CONTENT INTENT** is off — see [§3.2](#32-turn-on-the-message-content-intent). The log says so explicitly. |
| `Discord rejected the bot token` | Wrong or revoked token. Reset it (**Bot** → **Reset Token**) and update `config.yaml`. |
| Bot replies `Unauthorized.` | Your user ID isn't in `allowed_user_ids`. Re-copy it with Developer Mode on. |
| Nothing happens in a channel | You have to **@-mention** the bot in channels. DMs need no mention. |
| Can't DM the bot | You don't share a server with it yet — re-run the invite URL from [§3.4](#34-invite-the-bot-to-a-server). |
| Tools don't appear in the `/` picker | The bot was invited without the **`applications.commands`** scope — re-run the invite URL from [§3.4](#34-invite-the-bot-to-a-server) with it ticked. Or the tool was added after startup: restart LeSysBot. |

---

## 4. Building a custom adapter

To support another platform, subclass `MessagingAdapter`
(`lesysbot/messaging/base.py`) and implement `start()` and `send()`. Override
`confirm()` to add a confirmation UI (the default auto-approves; the CLI,
Telegram and Discord adapters all override it). `split_message()` from the same
module chunks a long reply to whatever length limit your platform enforces.

If your platform has a native command menu, take the tool registry as an
optional second constructor argument and build the menu from
`lesysbot/messaging/commands.py`: `all_commands(registry)` gives you name,
description and typed parameters per tool, and `to_slash_text(name, kwargs)`
renders an invocation back into the `/name key=value` form so it re-enters the
one dispatch path in `Agent._handle_slash` instead of you writing a second one.

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
