# Control panel

A web page for your settings and tools, always at:

```
http://127.0.0.1:8700
```

The [background service](service.md) keeps it online. It's only reachable from
this machine.

## What you can do

| Tab | What it's for |
|---|---|
| **Status** | Is the model reachable, is the service running, where is Grafana |
| **Marketplace** | Browse and install tools and dashboards |
| **Tools** | Turn tools on or off (applies within a second), or remove them |
| **Dashboards** | See which Grafana dashboards are ready, and render them |
| **Doctor** | What's missing on this machine, and how to fix it |
| **Config** | Edit `config.yaml` — checked before saving; restart the service to apply |

## It says offline

The service isn't running. Start it:

```bash
systemctl --user start lesysbot
```

Or run the panel from your terminal until you close it:

```bash
lesysbot manage --open
```

## Status in the terminal

`lesysbot` on its own prints the same status and exits:

```
    LLM backend  reachable · 42 ms
       Provider  cli · model qwen3.5:4b
          Tools  14/15 enabled
        Service  running (PID 12934)
  Control panel  online · http://127.0.0.1:8700
        Grafana  http://localhost:3000
         Config  /home/you/.lesysbot/config.yaml
```

## Is it safe?

On a machine only you use, yes.

- It listens on `127.0.0.1` only — never on your network — and rejects requests
  that don't come from localhost.
- It has no login. Anyone who can open it on this machine could also edit
  `config.yaml` directly.
- It shows your config, tokens included. To hide them, keep tokens in
  environment variables — see [Settings](configuration.md#keep-secrets-out-of-the-file).

Don't forward the port to other machines.

## Change the port

```yaml
management:
  port: 8700
```

Restart the service to apply.
