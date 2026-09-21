---
name: speedtest
description: Measure current internet download speed and latency
requires: []
---
# speedtest

Measures your **current internet connection speed** using Cloudflare's public
speed-test endpoints (`speed.cloudflare.com`) over the standard library — no
external binary, no pip dependency, just outbound internet.

**Needs:** nothing (outbound HTTPS)

## Tools
- `/speedtest [size_mb]` — download throughput (Mbps) and latency (ms). `size_mb`
  is how much to fetch (default `10`; larger is more accurate but slower).

## Notes
Reports **download** speed and latency, not upload. The HTTP calls are blocking,
so they run in a worker thread to keep the bot responsive. A larger `size_mb`
gives a steadier reading on fast links but takes longer.

## Copy-paste
Drop this `speedtest/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
