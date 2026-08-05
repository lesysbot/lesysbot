from __future__ import annotations

import functools
import importlib
import importlib.util
import json
import logging
import sys
import sysconfig
from pathlib import Path
from typing import Any, Callable

from lesysbot.core.paths import force_rmtree
from lesysbot.mcp.cli_tool import CLITool
from lesysbot.mcp.platform import availability

logger = logging.getLogger(__name__)


def _make_stub(name: str, reason: str) -> Callable:
    """Return an async fn that explains why a gated tool can't run here."""
    async def _stub(**_kwargs: Any) -> str:
        return f"'{name}' is unavailable on this machine — {reason}."
    return _stub


_TRUTHY = frozenset({"true", "yes", "y", "1", "on"})
_FALSY = frozenset({"false", "no", "n", "0", "off"})


def coerce_arguments(
    properties: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    """Coerce string arguments to the JSON types the tool declared.

    Arguments reach a tool as text from two directions that can't type them:
    a `/tool size_mb=10` slash command is parsed out of a chat message, and an
    LLM emitting tool-call JSON routinely quotes numbers. Without this, a tool
    annotated `size_mb: float` is handed `"10"` and either raises deep inside or
    silently does string arithmetic.

    Only *strings* are converted, and only where the declared type says to —
    values that already arrive correctly typed pass through untouched. Raises
    :class:`ValueError` with a message meant for the user when a value can't be
    converted; `call()` returns that instead of letting a traceback surface.
    """
    coerced: dict[str, Any] = {}
    for key, value in arguments.items():
        want = (properties.get(key) or {}).get("type")
        if not isinstance(value, str) or want in (None, "string"):
            coerced[key] = value
            continue
        text = value.strip()
        if want == "integer":
            coerced[key] = _to_int(key, text)
        elif want == "number":
            coerced[key] = _to_float(key, text)
        elif want == "boolean":
            coerced[key] = _to_bool(key, text)
        else:
            # array/object — a chat argument has no sane textual form for these,
            # so pass the string through and let the tool decide.
            coerced[key] = value
    return coerced


def _to_int(key: str, text: str) -> int:
    try:
        return int(text)
    except ValueError:
        # "3.0" from an LLM means 3; "3.5" for an int parameter does not.
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"{key} must be a whole number, got {text!r}") from None
        if not number.is_integer():
            raise ValueError(f"{key} must be a whole number, got {text!r}") from None
        return int(number)


def _to_float(key: str, text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {text!r}") from None


def _to_bool(key: str, text: str) -> bool:
    low = text.lower()
    if low in _TRUTHY:
        return True
    if low in _FALSY:
        return False
    raise ValueError(f"{key} must be true or false, got {text!r}")


@functools.cache
def _stdlib_dirs() -> tuple[str, ...]:
    """Interpreter-owned import roots — fixed for the life of the process."""
    paths = sysconfig.get_paths()
    return tuple(
        p for p in (paths.get(k) for k in ("stdlib", "platstdlib", "purelib", "platlib")) if p
    )


def _drop_user_helpers() -> None:
    """Evict cached top-level ``_``-prefixed *user* helper modules (e.g. a tool's
    ``_helpers``), leaving stdlib/site modules (``_thread``, ``_py_abc``, …) alone.

    Tool helpers are imported by their bare name, so the import system caches them
    globally; dropping ours forces a package to re-import the ``_helpers`` sitting
    next to it rather than reusing one cached from a different package or dir.
    """
    std = _stdlib_dirs()
    for name in list(sys.modules):
        if not (name.startswith("_") and "." not in name):
            continue
        mod = sys.modules.get(name)
        mod_file = getattr(mod, "__file__", None)
        if not mod_file or mod_file.startswith(std):
            continue
        sys.modules.pop(name, None)


class ToolRegistry:
    """Discovers, registers, and hot-reloads tools from a directory."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        # Names the user has turned off via `lesysbot tools disable`. Disabled
        # tools stay registered (so they're listed) but are hidden from the LLM and
        # refuse to run. This set is an instance attr, so it survives reload() (hot-reload);
        # _state_path persists it across process restarts.
        self._disabled: set[str] = set()
        self._state_path: Path | None = None
        # Resolved tools dir of the last load_directory() — the root that
        # tool_source()/remove_tool() map tool names back to files under.
        self._dir: Path | None = None

    # -- enable/disable -----------------------------------------------------

    def is_enabled(self, name: str) -> bool:
        return name not in self._disabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        self._save_state()

    def enable(self, name: str) -> None:
        self.set_enabled(name, True)

    def disable(self, name: str) -> None:
        self.set_enabled(name, False)

    def set_state_path(self, path: str | Path | None) -> None:
        self._state_path = Path(path) if path else None

    def load_state(self) -> None:
        """Load the persisted set of disabled tools, if a state file exists."""
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
            self._disabled = set(data.get("disabled", []))
            logger.info("Loaded tool state: %d disabled", len(self._disabled))
        except Exception:
            logger.exception("Failed to load tool state from %s", self._state_path)

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"disabled": sorted(self._disabled)}, indent=2))
        except Exception:
            logger.exception("Failed to save tool state to %s", self._state_path)

    # -----------------------------------------------------------------------

    def register(self, tool_meta: dict[str, Any], source: Path | None = None) -> None:
        name = tool_meta["name"]
        if source is not None:
            tool_meta["source"] = str(source)
        # Gate on declared platforms / required executables. Unsupported tools are
        # still registered (visible in /help and to the LLM) but their fn is swapped
        # for a stub that explains why they can't run here.
        ok, reason = availability(tool_meta.get("platforms"), tool_meta.get("requires"))
        tool_meta["available"] = ok
        tool_meta["unavailable_reason"] = reason
        if not ok:
            tool_meta["fn"] = _make_stub(name, reason or "unavailable here")
            logger.info("Tool '%s' gated: %s", name, reason)
        self._tools[name] = tool_meta
        logger.debug("Registered tool: %s", name)

    def register_callable(self, obj: Any, source: Path | None = None) -> None:
        """Register a @tool-decorated function or CLITool instance."""
        if isinstance(obj, CLITool):
            self.register(obj.__tool_meta__, source=source)
            return
        meta = getattr(obj, "__tool_meta__", None)
        if isinstance(meta, dict):
            self.register(meta, source=source)

    def load_directory(self, tools_dir: str | Path) -> None:
        """Discover tools in tools_dir.

        Two layouts are supported:
          • folder packages — each subdirectory (e.g. ``gpu-temp/``) is a
            self-contained, copy-paste tool with its own ``README.md`` and
            ``tool.py``. This is the recommended, shareable form.
          • loose ``.py`` files dropped straight in ``tools/`` (quick local tools).
        """
        directory = Path(tools_dir)
        self._dir = directory.resolve()
        if not directory.exists():
            logger.warning("Tools directory does not exist: %s", directory)
            return

        # Put the tools directory on sys.path so loose tool files can import sibling
        # helper modules (e.g. `from _helpers import ...`).
        dir_str = str(directory.resolve())
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)

        # Loose .py files (back-compatible quick tools).
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            self._load_file(py_file)

        # Folder packages — one self-contained tool per subdirectory.
        for sub in sorted(directory.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")) and sub.name != "__pycache__":
                self._load_package(sub)

    def _load_package(self, package: Path) -> None:
        """Import the tool modules inside a folder package.

        The package dir is put on sys.path so its files can do
        ``from _helpers import ...``. User helper modules are cleared both before
        and after so each package resolves its *own* ``_helpers.py`` — two packages
        can ship a like-named helper without clobbering one another, and a helper
        cached from another tools dir can't shadow this package's.
        """
        py_files = [p for p in sorted(package.glob("*.py")) if not p.name.startswith("_")]
        if not py_files:
            return

        pkg_str = str(package.resolve())
        added = pkg_str not in sys.path
        if added:
            sys.path.insert(0, pkg_str)
        _drop_user_helpers()
        try:
            for py_file in py_files:
                self._load_file(py_file, prefix=f"_lesysbot_tools.{package.name}")
        finally:
            _drop_user_helpers()
            if added and pkg_str in sys.path:
                sys.path.remove(pkg_str)

    def _load_file(self, path: Path, prefix: str = "_lesysbot_tools") -> None:
        module_name = f"{prefix}.{path.stem}"
        try:
            # Remove old module so hot-reload works
            sys.modules.pop(module_name, None)

            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[attr-defined]

            found = 0
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if _is_tool(obj):
                    self.register_callable(obj, source=path.resolve())
                    found += 1

            if found:
                logger.info("Loaded %d tool(s) from %s", found, path.name)
        except Exception:
            logger.exception("Failed to load tools from %s", path)

    def reload(self, tools_dir: str | Path) -> None:
        """Reload all tools from directory (hot-reload)."""
        self._tools.clear()
        self._invalidate_cached_modules(tools_dir)
        importlib.invalidate_caches()
        self.load_directory(tools_dir)
        logger.info("Tools reloaded: %d available", len(self._tools))

    @staticmethod
    def _invalidate_cached_modules(tools_dir: str | Path) -> None:
        """Drop cached sibling modules (e.g. `_helpers`) imported from the tools
        directory so edits to them are picked up on the next reload."""
        root = str(Path(tools_dir).resolve())
        for name, module in list(sys.modules.items()):
            mod_file = getattr(module, "__file__", None)
            if mod_file and mod_file.startswith(root):
                sys.modules.pop(name, None)

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format.

        Disabled tools are omitted so the LLM can't see or call them.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": meta["name"],
                    "description": meta["description"],
                    "parameters": meta["parameters"],
                },
            }
            for meta in self._tools.values()
            if self.is_enabled(meta["name"])
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self._tools:
            return f"Unknown tool: {name}"
        if not self.is_enabled(name):
            return f"Tool '{name}' is disabled. Run `lesysbot tools enable {name}` to use it."
        meta = self._tools[name]
        fn: Callable = meta["fn"]
        try:
            arguments = coerce_arguments(
                meta["parameters"].get("properties", {}), arguments
            )
        except ValueError as exc:
            # A wrong-typed argument is the caller's mistake, not a tool crash —
            # say which parameter and what it wanted.
            return f"Tool error: {exc}"
        try:
            result = await fn(**arguments)
            return str(result)
        except Exception as e:
            logger.exception("Tool %s raised an error", name)
            return f"Tool error: {e}"

    # -- source mapping & removal --------------------------------------------

    def _source_unit(self, source: str | None) -> Path | None:
        """The removable unit a source file belongs to: the folder package
        directly under the tools dir that contains it, or the loose ``.py``
        file itself. ``None`` when the source isn't under the tools dir."""
        if not source or not self._dir:
            return None
        try:
            rel = Path(source).relative_to(self._dir)
        except ValueError:
            return None
        return self._dir / rel.parts[0]

    def tool_source(self, name: str) -> dict[str, Any] | None:
        """Where a tool lives on disk, as its removable unit.

        Returns ``{path, kind, unit, tools}`` — ``kind`` is ``"package"`` or
        ``"file"``, ``tools`` is every registered tool sharing that unit (a
        package or loose file can define several) — or ``None`` when the tool
        wasn't loaded from the tools dir (e.g. registered programmatically).
        """
        meta = self._tools.get(name)
        if not meta:
            return None
        unit = self._source_unit(meta.get("source"))
        if unit is None:
            return None
        tools = sorted(
            n for n, m in self._tools.items() if self._source_unit(m.get("source")) == unit
        )
        return {
            "path": str(unit),
            "kind": "package" if unit.is_dir() else "file",
            "unit": unit.name,
            "tools": tools,
        }

    def remove_tool(self, name: str) -> dict[str, Any]:
        """Delete a tool's source from the tools dir — the whole folder package
        (or the loose ``.py`` file) — and deregister every tool it provided.

        Returns the pre-removal :meth:`tool_source` info. Raises ``KeyError``
        for an unknown tool and ``ValueError`` when it has no removable source.
        """
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        info = self.tool_source(name)
        if info is None:
            raise ValueError(
                f"'{name}' wasn't loaded from the tools directory — remove it where it's defined."
            )
        unit = Path(info["path"])
        # Belt-and-braces: never delete anything that isn't a direct child of
        # the tools dir, however the source path was recorded.
        if self._dir is None or unit.resolve().parent != self._dir:
            raise ValueError(f"Refusing to remove {unit} — not directly inside the tools dir")
        if unit.is_dir():
            force_rmtree(unit)
        elif unit.exists():
            unit.unlink()
        removed = set(info["tools"])
        for tool_name in removed:
            self._tools.pop(tool_name, None)
        if self._disabled & removed:
            self._disabled -= removed
            self._save_state()
        logger.info("Removed %s (tools: %s)", unit, ", ".join(info["tools"]))
        return info

    def tool_status(self) -> list[dict[str, Any]]:
        """Per-tool status for `lesysbot tools list`: enabled/available + gating metadata."""
        status = []
        for meta in self._tools.values():
            params = meta["parameters"].get("properties", {})
            required = meta["parameters"].get("required", [])
            status.append({
                "name": meta["name"],
                "description": meta["description"],
                "enabled": self.is_enabled(meta["name"]),
                "available": meta.get("available", True),
                "unavailable_reason": meta.get("unavailable_reason"),
                "platforms": meta.get("platforms"),
                "requires": meta.get("requires"),
                "confirm": bool(meta.get("confirm")),
                "params": [{"name": p, "required": p in required} for p in params],
                "source": self.tool_source(meta["name"]),
            })
        return status

    def get_tool_meta(self, name: str) -> dict[str, Any] | None:
        """Return the full raw tool metadata dict, or None if not found."""
        return self._tools.get(name)

    def get_tool_info(self, name: str) -> dict[str, Any] | None:
        """Return {name, description, param_names, required} for a tool, or None."""
        meta = self._tools.get(name)
        if not meta:
            return None
        params = meta["parameters"]
        return {
            "name": meta["name"],
            "description": meta["description"],
            "param_names": list(params.get("properties", {}).keys()),
            "required": params.get("required", []),
        }

    def list_tools_text(self) -> str:
        """Return a human-readable list of tools with their signatures."""
        if not self._tools:
            return "No tools registered."
        lines = ["Available commands — use /help to see this list\n"]
        for meta in self._tools.values():
            params = meta["parameters"].get("properties", {})
            required = meta["parameters"].get("required", [])
            parts = []
            for p in params:
                parts.append(f"<{p}>" if p in required else f"[{p}]")
            sig = " ".join(parts)
            entry = f"/{meta['name']}"
            if sig:
                entry += f" {sig}"
            entry += f"\n  {meta['description']}"
            if not self.is_enabled(meta["name"]):
                entry += "\n  ⊘ disabled (`lesysbot tools enable` to re-enable)"
            if not meta.get("available", True):
                entry += f"\n  ⚠ unavailable here: {meta.get('unavailable_reason')}"
            lines.append(entry)
        return "\n\n".join(lines)

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())


def _is_tool(obj: Any) -> bool:
    if isinstance(obj, CLITool):
        return True
    # @tool-decorated functions have __tool_meta__ set as a plain dict attribute
    return callable(obj) and isinstance(getattr(obj, "__tool_meta__", None), dict)
