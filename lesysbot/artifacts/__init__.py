"""Artifact install system: fetch tool and dashboard packages from GitHub.

Submodules are imported lazily by the CLI; keep this init dependency-free so
importing :mod:`lesysbot.artifacts` stays cheap for the bot process.
"""

__all__ = ["ArtifactKind", "ToolInstallError"]

from lesysbot.artifacts.errors import ToolInstallError
from lesysbot.artifacts.kinds import ArtifactKind
