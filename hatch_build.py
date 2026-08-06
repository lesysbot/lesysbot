"""Build hook: stage bundled content into the wheel without machine-local state.

`tools/`, `dashboard/`, `dashboards/` and `catalog.json` have to reach an
installed LeSysBot — otherwise `pip install lesysbot` gives you a bot with no
tools and no dashboards. They live at the repo root rather than under the
package because they are also the files people edit, link to from the docs, and
copy out as examples.

Hatchling's `force-include` copies a directory *literally*, and its `exclude`
patterns do not apply to it. That matters here because several paths inside
`dashboard/` are git-ignored local state that happens to sit in the tree:

* **`.env` holds the Grafana admin password.** It is git-ignored for that
  reason. A release built on a machine where the password had been changed would
  otherwise ship that password to every user of the wheel. This is the whole
  reason the hook exists; the rest are merely wasteful.
* `bin/`, `run/`, `native/` — downloaded exporter binaries, PIDs and generated
  absolute-path config. Large, machine-specific, regenerated on first run.
* `grafana/dashboards/generated-*.json` — per-host dashboard cuts.

So the hook copies each tree into a temporary staging directory, dropping those,
and force-includes the *staged* copy instead.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

#: Top-level names copied into `lesysbot/_bundled/`.
BUNDLED = ("tools", "dashboard", "dashboards", "catalog.json")

#: Paths (relative to each bundled root) that must never reach a wheel.
EXCLUDED_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache",
                  "bin", "run", "native", ".DS_Store"}
EXCLUDED_FILES = {".env"}
EXCLUDED_GLOBS = ("generated-*.json",)


def _keep(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_NAMES for part in rel.parts):
        return False
    if path.name in EXCLUDED_FILES:
        return False
    return not any(path.match(pattern) for pattern in EXCLUDED_GLOBS)


# hatchling is a *build* dependency: it exists while a wheel is being built and
# generally not otherwise. The rules above are the part worth testing, and they
# need nothing from it — so the hook class is defined only when hatchling is
# importable, letting `tests/test_bundled.py` exercise `_keep` and `BUNDLED`
# in an ordinary test environment.
try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ModuleNotFoundError:      # pragma: no cover - not a build environment
    BuildHookInterface = object


class BundleHook(BuildHookInterface):
    PLUGIN_NAME = "bundle"

    def initialize(self, version, build_data):
        root = Path(self.root)
        staging = Path(tempfile.mkdtemp(prefix="lesysbot-bundle-"))
        # Held on the instance so it survives until finalize(); deleting it here
        # would pull the files out from under the builder.
        self._staging = staging

        for name in BUNDLED:
            source = root / name
            if not source.exists():
                continue
            target = staging / name
            if source.is_file():
                shutil.copy2(source, target)
            else:
                shutil.copytree(
                    source, target,
                    ignore=lambda directory, entries: {
                        e for e in entries
                        if not _keep(Path(directory) / e, source)
                    },
                )
            build_data["force_include"][str(target)] = f"lesysbot/_bundled/{name}"

    def finalize(self, version, build_data, artifact_path):
        shutil.rmtree(getattr(self, "_staging", ""), ignore_errors=True)
