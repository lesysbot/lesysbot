"""Startup notice — ping the user when the bot comes up.

For an installed background service the bot starts when the machine boots, so
this is effectively a "the system just woke up" message: a short report with
CPU/GPU temperature, disk usage, and internet speed (each only if the host can
answer — see `core/sysinfo.py`).

`__main__._run` spawns `send_startup_notice()` as a background task beside the
messaging adapter (remote providers only; the CLI has the user right there). It
waits for the adapter's `ready` event, builds the report, and `send()`s it to
each configured recipient, retrying a couple of times since the network may
still be settling right after boot.
"""

from __future__ import annotations

import asyncio
import logging

from lesysbot.core import sysinfo
from lesysbot.core.config import Settings
from lesysbot.messaging.base import MessagingAdapter

logger = logging.getLogger(__name__)

_READY_TIMEOUT = 120.0  # seconds to wait for the adapter to come up
_SEND_ATTEMPTS = 3
_SEND_RETRY_DELAY = 10.0


def resolve_recipients(settings: Settings) -> list[str]:
    """Who to ping: `startup_notice.notify`, else the provider's allow-list.

    Both remote providers keep a list of the people allowed to use the bot, and
    those are exactly the people who want the boot report — so an empty `notify`
    falls back to it rather than sending nothing. A Discord `notify` entry may
    also be a channel id; the adapter resolves either (see
    `DiscordAdapter._destination`)."""
    cfg = settings.messaging.startup_notice
    if cfg.notify:
        return [str(r) for r in cfg.notify]
    provider = settings.messaging.provider
    if provider == "telegram":
        return [str(uid) for uid in settings.messaging.telegram.allowed_user_ids]
    if provider == "discord":
        return [str(uid) for uid in settings.messaging.discord.allowed_user_ids]
    return []


async def send_startup_notice(adapter: MessagingAdapter, settings: Settings) -> None:
    cfg = settings.messaging.startup_notice
    recipients = resolve_recipients(settings)
    if not recipients:
        logger.info(
            "Startup notice enabled but no recipients — set "
            "messaging.startup_notice.notify in config.yaml"
        )
        return

    try:
        await asyncio.wait_for(adapter.ready.wait(), timeout=_READY_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Startup notice skipped — adapter not ready after %.0fs", _READY_TIMEOUT)
        return

    report = await sysinfo.startup_report(
        speedtest_mb=cfg.speedtest_mb if cfg.speedtest else None
    )

    for user_id in recipients:
        for attempt in range(1, _SEND_ATTEMPTS + 1):
            try:
                await adapter.send(user_id, report)
                logger.info("Startup notice sent to %s", user_id)
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Startup notice to %s failed (attempt %d/%d): %s",
                    user_id, attempt, _SEND_ATTEMPTS, exc,
                )
                if attempt < _SEND_ATTEMPTS:
                    await asyncio.sleep(_SEND_RETRY_DELAY)
