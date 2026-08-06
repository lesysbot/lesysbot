"""Service checks must consult the stack's configured ports, not just defaults.

Found on a live machine: Prometheus had been moved to 9091 (recorded in the
stack's `.env`, which is where that is recorded), but `check_service` consulted
`.env` for Grafana only. Prometheus therefore reported as "not running" while it
was running perfectly — and a dashboard depending on it would have been withheld
as unavailable. A false negative here is exactly the failure the prerequisite
layer exists to prevent, pointed the wrong way.
"""

from __future__ import annotations

import pytest

from lesysbot.prereq import Requirement, check
from lesysbot.prereq import checks as checks_mod


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """A stack dir whose .env moves both services off their default ports."""
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / ".env").write_text("PROM_PORT=9091\nGRAFANA_PORT=3001\n")
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("service,port", [("prometheus", 9091), ("grafana", 3001)])
def test_configured_port_is_used(stack, monkeypatch, service, port):
    seen = []
    monkeypatch.setattr(checks_mod, "_listening",
                        lambda h, p, **k: seen.append(p) or True)
    result = check(Requirement("service", service))
    assert seen == [port]
    assert result.satisfied and str(port) in result.detail


@pytest.mark.parametrize("service,port", [("prometheus", 9090), ("grafana", 3000),
                                          ("ollama", 11434)])
def test_default_port_when_env_is_silent(tmp_path, monkeypatch, service, port):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    seen = []
    monkeypatch.setattr(checks_mod, "_listening",
                        lambda h, p, **k: seen.append(p) or True)
    check(Requirement("service", service))
    assert seen == [port]


def test_metric_check_uses_the_same_configured_port(stack, monkeypatch):
    """`check_metric` and `check_service` must agree about where Prometheus is."""
    seen = []
    monkeypatch.setattr(checks_mod, "_listening",
                        lambda h, p, **k: seen.append(p) or False)
    result = check(Requirement("metric", "up"))
    assert seen == [9091]
    assert not result.satisfied and "Prometheus is not running" in result.detail


def test_literal_host_port_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    seen = []
    monkeypatch.setattr(checks_mod, "_listening",
                        lambda h, p, **k: seen.append((h, p)) or True)
    check(Requirement("service", "example.internal:8080"))
    assert seen == [("example.internal", 8080)]
