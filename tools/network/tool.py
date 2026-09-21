"""Network tools — shell commands wrapped as bot tools.

Each tool is gated on its own binary, so a box missing `traceroute` still gets
working `ping` and `dns_lookup`; the gated one registers but explains itself
rather than failing with a shell error.
"""
from lesysbot.mcp import CLITool

ping = CLITool(
    name="ping",
    description="Ping a host to check connectivity and measure latency",
    command="ping -c 3 {host}",
    params={"host": "Hostname or IP address to ping"},
    timeout=15.0,
    requires=["ping"],
)

dns_lookup = CLITool(
    name="dns_lookup",
    description="Resolve a domain name to its IP addresses",
    command="nslookup {domain}",
    params={"domain": "Domain name to resolve"},
    requires=["nslookup"],
)

traceroute = CLITool(
    name="traceroute",
    description="Trace the network path to a host",
    command="traceroute -m 15 {host}",
    params={"host": "Hostname or IP address to trace"},
    timeout=60.0,
    requires=["traceroute"],
)
