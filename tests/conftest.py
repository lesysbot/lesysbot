"""Suite-wide safety rails.

The tests construct real installers over temp directories, which is what makes
them worth having — but an installer's job now includes pip-installing a
package's dependencies, and there is no temp directory for *that*. It would run
against whatever interpreter the suite happens to be using, which on a
developer's machine is their actual environment.

So dependency installation is switched off for the entire suite here rather than
per test. A test that wants to exercise it stubs `subprocess.run` and clears the
variable itself; everything else cannot accidentally reach the network or mutate
site-packages.
"""

from __future__ import annotations

import pytest

from lesysbot.artifacts import deps


@pytest.fixture(autouse=True)
def _no_real_pip_installs(monkeypatch):
    monkeypatch.setenv(deps.SKIP_ENV, "1")


@pytest.fixture(autouse=True)
def _ports_are_free(monkeypatch):
    """Every port reads as free unless a test says otherwise.

    The setup wizard moves Grafana off a taken port, and whether 3000 is taken
    depends on the developer's machine — so without this the wizard's prompts
    (and thus every scripted wizard test) would change with what happens to be
    running. Tests of the port logic patch ``port_in_use`` again, or import it
    at module level (before this fixture swaps the attribute) to get the real one.
    """
    from lesysbot.core import grafana

    monkeypatch.setattr(grafana, "port_in_use", lambda port, host="127.0.0.1": False)
