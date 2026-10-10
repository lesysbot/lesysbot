# Security

LeSysBot can power off your machine and it listens on a chat network. These are
the four things that keep that safe.

## 1. Only you can use the bot

Anyone who finds your Telegram or Discord bot can message it. The allow-list
decides who gets an answer:

```yaml
messaging:
  telegram:
    allowed_user_ids: [123456789]
```

**An empty list lets anyone in** — and run every tool you have. `lesysbot setup`
won't accept an empty list, but check it if you edit the file by hand. On
Discord this matters even more: anyone who shares a server with the bot can DM
it.

## 2. Tools are code you trust

A tool runs as your user, with no sandbox — installing one is like
`pip install`. Install from people you trust, pin a version (`owner/repo@v1.0`),
and skim `tool.py` before you say yes.

Confirmations protect you from the *model* making a mistake, not from a harmful
tool. The shutdown tools also wait a minute, so you can still cancel.

## 3. Secrets stay out of files and logs

Keep tokens in the environment instead of `config.yaml`:

```yaml
token: ${TELEGRAM_TOKEN}
```

Tokens and keys are removed from the logs automatically. `traces.jsonl` does
record what your tools returned, so read it before sharing it.

## 4. Nothing is exposed to your network

The bot opens no port. What does listen is bound to `127.0.0.1`:

| What | Where | Notes |
|---|---|---|
| [Control panel](management-ui.md) | `127.0.0.1:8700` | No login — anyone on this machine can use it. It shows your config, tokens included. |
| [Grafana](dashboards.md) | `127.0.0.1:3000` | Uses the login from setup. Change it if it's still `admin`/`admin`. |

If you ever need either from another machine, use an SSH tunnel or a reverse
proxy with TLS and a login. Don't change the bind address.

**Shared dashboard snapshots are public.** Anyone with the link can see them
until they expire or you delete them.

## Checklist

- [ ] `allowed_user_ids` holds only your own ID.
- [ ] Tokens live in environment variables.
- [ ] You've read any tool you didn't write before installing it.
- [ ] Grafana's password isn't `admin`.
- [ ] Ports 8700 and 3000 aren't forwarded to the internet.
