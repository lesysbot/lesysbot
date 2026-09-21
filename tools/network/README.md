---
name: network
description: Ping, DNS lookup, and traceroute
version: 1.0.0
requires: [ping, nslookup, traceroute]
---
# network

Basic network diagnostics wrapped as shell-command tools. Each tool is gated
on its own binary, so a box without `traceroute` installed still gets working
`ping` and `dns_lookup` — the gated one stays listed and explains itself.

**Needs:** `ping`, `nslookup`, `traceroute` on PATH

## Tools
- `/ping <host>` — connectivity + latency (`ping -c 3`).
- `/dns_lookup <domain>` — resolve a domain to IPs (`nslookup`).
- `/traceroute <host>` — trace the network path (`traceroute -m 15`).

## Copy-paste
Drop this `network/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
