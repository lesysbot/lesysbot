from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from lesysbot.mcp._legacy import linux_command, note_platforms


@dataclass
class CLITool:
    """Wrap a shell command as an MCP tool.

    Example:
        ping_tool = CLITool(
            name="ping",
            description="Ping a host to check connectivity",
            command="ping -c 3 {host}",
            params={"host": "The hostname or IP to ping"},
            confirm="This will send network packets — proceed?",
        )

    ``requires`` names executables the command needs on PATH, so a tool whose
    binary is missing registers as an explaining stub instead of failing with a
    shell error:

        ping_tool = CLITool(
            name="mtr",
            description="Trace the route to a host",
            command="mtr --report --report-cycles 5 {host}",
            params={"host": "The hostname or IP to trace"},
            requires=["mtr"],
        )

    ``platforms``, and an OS-keyed dict for ``command``, are accepted and
    ignored so packages written against the older API keep loading; see
    :mod:`lesysbot.mcp._legacy`.
    """
    name: str
    description: str
    command: str | dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    confirm: bool | str = False
    requires: list[str] | None = None
    platforms: list[str] | None = None   # legacy, ignored — see mcp/_legacy.py

    @property
    def __tool_meta__(self) -> dict[str, Any]:
        note_platforms(self.name, self.platforms)
        properties = {k: {"type": "string", "description": v} for k, v in self.params.items()}
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(self.params.keys()),
            },
            "fn": self._run,
            "confirm": self.confirm,
            "requires": self.requires,
        }

    async def _run(self, **kwargs: Any) -> str:
        template = linux_command(self.name, self.command)
        if not template:
            return f"Error: '{self.name}' has no command for Linux"
        try:
            cmd = template.format(**kwargs)
        except KeyError as e:
            return f"Error: missing parameter {e}"

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            return stdout.decode(errors="replace").strip()
        except asyncio.TimeoutError:
            return f"Error: command timed out after {self.timeout}s"
        except Exception as e:
            return f"Error running command: {e}"
