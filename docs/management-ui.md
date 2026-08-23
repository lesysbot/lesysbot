# Control panel

A small web page that does in a browser what the `lesysbot` command does in a
terminal: answer "is it working?", turn tools on and off, install new ones, and
edit your settings. If you'd rather click than type, start here.

**It is always on.** The LeSysBot background service serves it, so it is there
whenever your machine is, at the same address every time:

```
http://127.0.0.1:8700
```

Bookmark it. It runs on your machine only — nothing about it is reachable from
your network.

---

## Checking it's up

Run `lesysbot` with no arguments. That prints health and metrics and exits — it
starts nothing, because the panel is already running:

```bash
lesysbot
```

```
[the LeSysBot mark, in colour]  LeSysBot
                                v0.1.0

    LLM backend  reachable · 42 ms
    Backend URL  http://localhost:11434/v1
       Provider  cli · model qwen3.5:4b
          Tools  12/13 enabled
        Service  running (PID 12934)
  Control panel  online · http://127.0.0.1:8700
        Grafana  http://localhost:3001 · v11.5.1
         Config  /home/you/.lesysbot/config.yaml
```

The mark is drawn in colour when your terminal supports it. It disappears on its
own under `NO_COLOR`, a plain `TERM`, or when you pipe the output somewhere —
so `lesysbot > status.txt` stays readable.

If the panel says **offline**, the service isn't running — start it the way
[Background service](service.md) describes, or open the panel by hand for as
long as your terminal stays open:

```bash
lesysbot manage             # serve it here (or just point at the running one)
lesysbot manage --open      # and open it in your browser
lesysbot manage --port 9000 # a different port, e.g. for a second checkout
```

> **Looking for a chat?** None of these are a conversation. Use
> `lesysbot chat` to chat in your terminal.

---

## What you can do with it

Six tabs across the top, each the browser version of something you can also do
from the terminal:

| Tab | What's there | The terminal equivalent |
|---|---|---|
| **Status** | Is the model reachable and how fast, which provider and model are live, how many tools are on, whether the service is up, a link to [Grafana](../dashboard/README.md) if the stack is running, and where your config and tools actually are. | `lesysbot` |
| **Marketplace** | Browse the catalog and install a package with one click. | `lesysbot search` / `install` |
| **Tools** | Every tool with its state. Enable or disable with one click — a running bot picks it up within a second. Install by pasting `owner/repo`; remove a package, files and all. | `lesysbot list` / `enable` / `disable` / `remove` |
| **Dashboards** | Which dashboard is installed (there is exactly one), whether it can render on this machine, and whether it's been provisioned. **Render** hands it to Grafana; **Reset to default** puts the bundled one back. | `lesysbot dashboard current` / `render` / `reset` |
| **Doctor** | What a package needs, whether this machine has it, and the exact fix when it doesn't. | `lesysbot doctor` |
| **Config** | Your `config.yaml` in an editor, with tokens and API keys hidden. Saving validates first and refuses to write something invalid, so a typo can't lock you out. | edit `~/.lesysbot/config.yaml` |

**What applies immediately, and what doesn't:** turning a tool on or off reaches
a running bot within a second. Everything in **Config** takes effect when the
service next restarts — the panel says so when you save.

The toggle in the top-right switches between light and dark. It follows your
system setting until you pick one, then remembers your choice.

---

## Is this safe to leave running?

Yes, on a machine only you use — that's the assumption it's built on, and it is
why the panel can stay up permanently.

- **It's localhost-only.** The server binds `127.0.0.1`. The host isn't
  configurable, only the port, so it can't accidentally end up on your LAN. It
  also rejects any request whose `Host` header isn't localhost, which blocks a
  malicious web page from reaching it through your browser.
- **There's no login.** Anyone who can open `http://127.0.0.1:8700` on the
  machine can use it — but they could equally just edit `config.yaml`. That's
  the trust boundary, and it's the same one.
- **It doesn't show your tokens.** The Config tab is your real config file, but
  every bot token and API key in it arrives as `****` plus its last four
  characters — enough to tell which key is which, not enough to use. Leave a
  masked value alone and the saved one is kept; type a new value and it
  replaces it. A `${VAR}` reference is shown as written, since the name is the
  point — see [Settings](configuration.md).

Don't forward the port or put it behind a reverse proxy unless you add
authentication and TLS yourself.

The panel lives inside the LeSysBot service process — it is the one listener in
the project, and it only ever listens on loopback.

---

## Moving it to another port

Only the port is configurable:

```yaml
management:
  port: 8700
```

Change it and restart the service; the panel moves with it, and `lesysbot`
reports the new address. If something else already owns the port when the
service starts, the panel is skipped (a line in the log says so) and the bot
keeps running — see [Troubleshooting](troubleshooting.md).
