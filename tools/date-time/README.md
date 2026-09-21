---
name: date-time
description: Current date, time, and timezone info
requires: []
version: "1.0.0"
---
# date-time

Tells LeSysBot what day and time it is — locally or in any IANA timezone.
Pure-Python (stdlib only).

**Needs:** nothing

## Tools
- `/get_datetime [timezone]` — current date, time, and UTC offset. Pass an
  IANA name (e.g. `Europe/London`) to get the time somewhere else; omit it
  for the machine's local time.

## Copy-paste
Drop this `date-time/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
