"""Entry-point helpers (lesysbot/__main__.py)."""
from __future__ import annotations

import io

import pytest

from lesysbot.__main__ import _reconfigure_utf8


def test_reconfigure_utf8_makes_a_cp1252_stream_unicode_safe():
    """The Windows failure: a cp1252 stream can't encode ⚠ (which the tool list
    and banner emit), so Rich crashes mid-render. After reconfigure it writes
    UTF-8 and the glyph goes through cleanly."""
    # A fresh cp1252 stream is the crashing starting point.
    crasher = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    with pytest.raises(UnicodeEncodeError):
        crasher.write("⚠")
        crasher.flush()

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    _reconfigure_utf8(stream)
    assert stream.encoding.lower() == "utf-8"
    stream.write("⚠ ok")            # no longer raises
    stream.flush()
    assert "⚠ ok".encode("utf-8") in raw.getvalue()


def test_reconfigure_utf8_ignores_streams_without_reconfigure():
    """Replaced streams (pytest capture, plain objects) have no reconfigure —
    the helper must silently no-op, never raise."""
    _reconfigure_utf8(object())
