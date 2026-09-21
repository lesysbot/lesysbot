"""System info — basic machine details and free disk space.

Pure-Python (stdlib only), so it needs no extra dependencies.
"""
import platform
import shutil

from lesysbot.mcp import tool


@tool
async def get_system_info() -> str:
    """Return basic information about the current machine."""
    return (
        f"OS: {platform.system()} {platform.release()}\n"
        f"Python: {platform.python_version()}\n"
        f"Machine: {platform.machine()}"
    )


@tool(description="Check how much free disk space is available at a given path")
async def disk_usage(path: str) -> str:
    """Check free disk space at the given path."""
    try:
        usage = shutil.disk_usage(path)
        total_gb = usage.total / 1e9
        free_gb = usage.free / 1e9
        used_pct = (usage.used / usage.total) * 100
        return f"Path: {path}\nTotal: {total_gb:.1f} GB\nFree: {free_gb:.1f} GB\nUsed: {used_pct:.1f}%"
    except FileNotFoundError:
        return f"Path not found: {path}"
