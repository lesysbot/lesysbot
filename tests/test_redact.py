from __future__ import annotations

import logging

import pytest

from lesysbot.core import redact as redact_mod
from lesysbot.core.redact import (
    PLACEHOLDER,
    RedactingFilter,
    RedactingFormatter,
    add_secret,
    redact,
    register_settings_secrets,
)
from lesysbot.core.config import Settings

# A fabricated placeholder matching the Telegram token shape (digits:35 chars).
# NOT a real credential — do not paste a live BotFather token here.
TOKEN = "0000000000:AA-FAKE-placeholder-not-a-real-token-00"
GETUPDATES = f"HTTP Request: POST https://api.telegram.org/bot{TOKEN}/getUpdates"


@pytest.fixture(autouse=True)
def _clean_secrets():
    """Registered secrets are process-global; keep tests independent."""
    saved = set(redact_mod._secrets)
    redact_mod._secrets.clear()
    yield
    redact_mod._secrets.clear()
    redact_mod._secrets.update(saved)


def test_telegram_token_in_url_is_redacted():
    out = redact(GETUPDATES)
    assert TOKEN not in out
    # The "bot" prefix survives so the line still reads as a Telegram call.
    assert f"bot{PLACEHOLDER}/getUpdates" in out


def test_bare_telegram_token_is_redacted():
    assert TOKEN not in redact(f"token={TOKEN} configured")


@pytest.mark.parametrize(
    "secret",
    [
        # Fabricated shapes that exercise the regexes but are structurally
        # implausible as real credentials (so secret scanners don't flag them).
        "xoxb-FAKE-not-a-real-slack-bot-token-placeholder",
        "xapp-FAKE-not-a-real-slack-app-token-placeholder",
        "sk-FAKE-not-a-real-openai-key-placeholder",
        "sk-proj-FAKE-not-a-real-openai-key-placeholder",
    ],
)
def test_token_shapes_are_redacted(secret):
    assert secret not in redact(f"using {secret} now")


def test_registered_secret_is_redacted():
    add_secret("super-secret-value-123")
    assert redact("key=super-secret-value-123") == f"key={PLACEHOLDER}"


def test_short_values_are_never_registered():
    """`llm.api_key` is "ollama" by default — redacting it would wreck the logs."""
    add_secret("ollama")
    add_secret("vllm")
    assert redact("talking to ollama via vllm") == "talking to ollama via vllm"


def test_redact_is_idempotent():
    once = redact(GETUPDATES)
    assert redact(once) == once


def test_filter_scrubs_message_and_args():
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP Request: POST %s",
        args=(f"https://api.telegram.org/bot{TOKEN}/getUpdates",),
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
    # Args folded into msg, so re-formatting cannot resurrect the token.
    assert record.args is None


def test_filter_leaves_clean_records_lazy():
    record = logging.LogRecord(
        name="lesysbot",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Tools loaded: %d",
        args=(7,),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert record.args == (7,)
    assert record.getMessage() == "Tools loaded: 7"


def test_formatter_scrubs_traceback():
    try:
        raise RuntimeError(f"connect failed for https://api.telegram.org/bot{TOKEN}/x")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="lesysbot",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="LLM error",
            args=None,
            exc_info=sys.exc_info(),
        )
    out = RedactingFormatter("%(message)s").format(record)
    assert TOKEN not in out
    assert "RuntimeError" in out


def test_register_settings_secrets_skips_default_api_key():
    settings = Settings()
    settings.messaging.telegram.token = TOKEN
    settings.llm.api_key = "ollama"
    register_settings_secrets(settings)
    assert TOKEN in redact_mod._secrets
    assert "ollama" not in redact_mod._secrets


def test_end_to_end_through_a_handler(tmp_path):
    """The real wiring: a handler with the filter must not write the token."""
    log_file = tmp_path / "test.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(message)s"))
    handler.addFilter(RedactingFilter())

    logger = logging.getLogger("test_redact_e2e")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info("HTTP Request: POST %s", f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    finally:
        logger.removeHandler(handler)
        handler.close()

    written = log_file.read_text(encoding="utf-8")
    assert TOKEN not in written
    assert PLACEHOLDER in written
