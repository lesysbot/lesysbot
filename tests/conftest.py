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
