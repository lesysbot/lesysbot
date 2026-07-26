"""Tests for the startup notice (lesysbot/messaging/notice.py): recipient
resolution, the send flow over a fake adapter, retries, and config defaults."""
from __future__ import annotations

from lesysbot.core.config import Settings
from lesysbot.messaging import notice
from lesysbot.messaging.base import MessagingAdapter


class FakeAdapter(MessagingAdapter):
    def __init__(self, fail_first: int = 0) -> None:
        self.sent: list[tuple[str, str]] = []
        self._fail_first = fail_first

    async def start(self, handler) -> None:  # pragma: no cover - unused
        pass

    async def send(self, user_id: str, text: str) -> None:
        if self._fail_first > 0:
            self._fail_first -= 1
            raise RuntimeError("boom")
        self.sent.append((user_id, text))


def _settings(**messaging) -> Settings:
    return Settings.model_validate({"messaging": messaging})


def _stub_report(monkeypatch, text: str = "REPORT") -> dict:
    seen: dict = {}

    async def fake_report(speedtest_mb=None):
        seen["speedtest_mb"] = speedtest_mb
        return text

    monkeypatch.setattr(notice.sysinfo, "startup_report", fake_report)
    return seen


# ── config & recipients ────────────────────────────────────────────────────


def test_startup_notice_enabled_by_default():
    cfg = Settings().messaging.startup_notice
    assert cfg.enabled is True
    assert cfg.speedtest is True
    assert cfg.notify == []


def test_recipients_default_to_telegram_allowlist():
    s = _settings(provider="telegram", telegram={"allowed_user_ids": [111, 222]})
    assert notice.resolve_recipients(s) == ["111", "222"]


def test_explicit_notify_wins_and_coerces_ints():
    s = _settings(
        provider="telegram",
        telegram={"allowed_user_ids": [111]},
        startup_notice={"notify": [333, "C0FFEE"]},
    )
    assert notice.resolve_recipients(s) == ["333", "C0FFEE"]


def test_recipients_default_to_discord_allowlist():
    s = _settings(provider="discord", discord={"allowed_user_ids": [444, 555]})
    assert notice.resolve_recipients(s) == ["444", "555"]


def test_cli_has_no_default_recipients():
    # The CLI never sends a startup notice, and no other provider has an
    # allow-list to fall back to.
    assert notice.resolve_recipients(_settings(provider="cli")) == []


# ── send flow ──────────────────────────────────────────────────────────────


async def test_notice_sends_report_to_each_recipient(monkeypatch):
    _stub_report(monkeypatch)
    adapter = FakeAdapter()
    adapter.ready.set()
    s = _settings(provider="telegram", telegram={"allowed_user_ids": [1, 2]})

    await notice.send_startup_notice(adapter, s)
    assert adapter.sent == [("1", "REPORT"), ("2", "REPORT")]


async def test_notice_without_recipients_sends_nothing(monkeypatch):
    _stub_report(monkeypatch)
    adapter = FakeAdapter()
    adapter.ready.set()

    # discord with an empty allow-list and no explicit notify: nobody to ping.
    await notice.send_startup_notice(adapter, _settings(provider="discord"))
    assert adapter.sent == []


async def test_notice_skipped_when_adapter_never_ready(monkeypatch):
    _stub_report(monkeypatch)
    monkeypatch.setattr(notice, "_READY_TIMEOUT", 0.01)
    adapter = FakeAdapter()  # ready never set
    s = _settings(provider="telegram", telegram={"allowed_user_ids": [1]})

    await notice.send_startup_notice(adapter, s)
    assert adapter.sent == []


async def test_notice_retries_failed_send(monkeypatch):
    _stub_report(monkeypatch)
    monkeypatch.setattr(notice, "_SEND_RETRY_DELAY", 0)
    adapter = FakeAdapter(fail_first=1)
    adapter.ready.set()
    s = _settings(provider="telegram", telegram={"allowed_user_ids": [1]})

    await notice.send_startup_notice(adapter, s)
    assert adapter.sent == [("1", "REPORT")]


async def test_notice_respects_speedtest_toggle(monkeypatch):
    seen = _stub_report(monkeypatch)
    adapter = FakeAdapter()
    adapter.ready.set()
    s = _settings(
        provider="telegram",
        telegram={"allowed_user_ids": [1]},
        startup_notice={"speedtest": False},
    )

    await notice.send_startup_notice(adapter, s)
    assert seen["speedtest_mb"] is None


async def test_notice_passes_speedtest_size(monkeypatch):
    seen = _stub_report(monkeypatch)
    adapter = FakeAdapter()
    adapter.ready.set()
    s = _settings(
        provider="telegram",
        telegram={"allowed_user_ids": [1]},
        startup_notice={"speedtest_mb": 2.5},
    )

    await notice.send_startup_notice(adapter, s)
    assert seen["speedtest_mb"] == 2.5
