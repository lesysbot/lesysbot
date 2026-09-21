"""Web tools — async HTTP fetch using httpx.

Pure Python — no system binary to install. `httpx` is a pip dependency, not a
system executable, so it isn't expressed as `requires=` (those are PATH binaries);
instead the tool checks for it at call time and tells you how to install it.
See requirements.txt.
"""
from lesysbot.mcp import tool


@tool(description="Fetch the text content of a URL")
async def fetch_url(url: str) -> str:
    """Fetch plain text content from a URL."""
    try:
        import httpx
    except ImportError:
        return "httpx not installed. Run: pip install httpx"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "LeSysBot/0.1"})
            resp.raise_for_status()
            # Return first 3000 chars to keep responses manageable
            text = resp.text[:3000]
            return f"[{resp.status_code}] {url}\n\n{text}"
    except Exception as e:
        return f"Error fetching {url}: {e}"
