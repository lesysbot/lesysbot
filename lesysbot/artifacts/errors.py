from __future__ import annotations


class ToolInstallError(Exception):
    """Base for user-facing tool-install errors (caught by the CLI)."""


class SpecError(ToolInstallError):
    """A tool source spec couldn't be parsed."""


class ArchiveError(ToolInstallError):
    """A downloaded archive is invalid or unsafe to extract."""


class FetchError(ToolInstallError):
    """An HTTP download failed. ``status`` is 0 for network-level errors."""

    def __init__(self, status: int, url: str, message: str = "") -> None:
        self.status = status
        self.url = url
        super().__init__(message or f"HTTP {status} for {url}")
