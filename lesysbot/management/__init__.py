"""The local control panel — a dependency-free web UI for LeSysBot's
config and tools, bound to loopback only. See :func:`lesysbot.management.server.serve`."""
from lesysbot.management.server import serve

__all__ = ["serve"]
