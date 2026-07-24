# Control panel

A small web page for the two things you change most — your **settings** and your
**tools** — plus a status screen that answers "is it working?" at a glance.

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
       Provider  cli · model llama3.2
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
> `lesysbot --provider cli` to chat in your terminal.

---

## What you can do with it

**Status** — whether your model backend is reachable and how fast it answers,
which provider and model are active, how many tools are on, whether the
background bot service is running, a link to your
[Grafana dashboard](../monitoring/README.md) if the monitoring stack is up, and
where your config and tools actually live.

**Tools** — every tool with its current state:

- **Enable / disable** with one click, applied to a running bot within a second.
- **Install** a package from GitHub by pasting `owner/repo`.
- **Remove** a package, files and all.

**Settings** — your `config.yaml` in an editor. Saving checks it first and
refuses to write something invalid, so you can't lock yourself out with a typo.
Most settings take effect the next time the bot starts; tool enable/disable is
the exception and applies immediately.

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
- **It shows your secrets**, because it shows your real config file. If that
  bothers you, keep tokens in environment variables and reference them as
  `${VAR}` — see [Settings](configuration.md).

Don't forward the port or put it behind a reverse proxy unless you add
authentication and TLS yourself.

The panel lives inside the LeSysBot service process — it is the one listener in
the project, and it only ever listens on loopback.

---

## Settings

Only the port:

```yaml
webui:
  port: 8700
```

Change it and restart the service; the panel moves with it, and `lesysbot`
reports the new address. If something else already owns the port when the
service starts, the panel is skipped (a line in the log says so) and the bot
keeps running — see [Troubleshooting](troubleshooting.md).
