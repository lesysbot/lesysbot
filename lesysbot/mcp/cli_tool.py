from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from lesysbot.mcp.platform import current_os


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

    ``command`` may also be a dict keyed by OS name (``linux`` | ``macos`` |
    ``windows``) when the same tool needs different syntax per platform:

        ping_tool = CLITool(
            name="ping",
            description="Ping a host",
            command={"linux": "ping -c 3 {host}", "macos": "ping -c 3 {host}",
                     "windows": "ping -n 3 {host}"},
            params={"host": "The hostname or IP to ping"},
        )

    With a dict command, ``platforms`` defaults to the dict's keys, so the tool
    gates itself off on any OS it has no command for.

    ``requires`` may be keyed by OS the same way, for the common case where the
    per-OS commands are the *same* tool under different binary names::

        traceroute = CLITool(
            name="traceroute",
            description="Trace the network path to a host",
            command={"linux": "traceroute -m 15 {host}",
                     "windows": "tracert -h 15 -w 1000 {host}"},
            params={"host": "…"},
            requires={"linux": ["traceroute"], "windows": ["tracert"]},
        )

    A flat list still means "needed on every OS". Keying it matters because a
    flat ``["traceroute"]`` would gate the tool off on Windows — where the
    command exists, just spelled ``tracert``.
    """
    name: str
    description: str
    command: str | dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    confirm: bool | str = False
    platforms: list[str] | None = None
    requires: list[str] | dict[str, list[str]] | None = None

    @property
    def __tool_meta__(self) -> dict[str, Any]:
        properties = {k: {"type": "string", "description": v} for k, v in self.params.items()}
        platforms = self.platforms
        if platforms is None and isinstance(self.command, dict):
            platforms = list(self.command)
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
            "platforms": platforms,
            "requires": self._required_binaries(),
        }

    def _command_template(self) -> str | None:
        """The command for the current OS, or None when this OS has none."""
        if isinstance(self.command, dict):
            return self.command.get(current_os())
        return self.command

    def _required_binaries(self) -> list[str] | None:
        """The binaries needed *here* — resolved before the registry sees them.

        Resolving in the tool keeps ``platform.availability()`` and the registry
        taking a flat list, so per-OS naming stays a detail of the tool that has
        it rather than something every consumer has to understand.
        """
        if isinstance(self.requires, dict):
            # An OS the dict doesn't mention needs nothing, matching how a dict
            # `command` treats the same gap — `platforms` is what gates the OS.
            return self.requires.get(current_os())
        return self.requires

    async def _run(self, **kwargs: Any) -> str:
        template = self._command_template()
        if template is None:
            return f"Error: '{self.name}' has no command for this OS ({current_os()})"
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
