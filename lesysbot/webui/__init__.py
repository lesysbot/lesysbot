"""The local management UI — a dependency-free web control panel for LeSysBot's
config and tools, bound to loopback only. See :func:`lesysbot.webui.server.serve`."""
from lesysbot.webui.server import serve

__all__ = ["serve"]
