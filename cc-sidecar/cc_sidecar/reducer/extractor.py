"""
Resource extraction: turn raw tool payloads into one-line descriptions.

ARCHITECTURE: Pattern-matched extraction keyed on tool_name.
WHY: The TUI and alert system need human-readable summaries, not raw JSON.
TRADEOFF: Lossy compression — detailed info lives in the raw event store.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from cc_sidecar.constants import TOOL_ALIASES


def normalize_tool_name(name: str) -> str:
    """
    Normalize tool name aliases.

    WHY: Task was renamed to Agent in Claude Code ~v2.1.50-63.
    Task(...) is retained as an alias upstream.
    """
    return TOOL_ALIASES.get(name, name)


def extract_resource(tool_name: str, tool_input: dict[str, Any]) -> str:
    """
    Turn a tool invocation into a one-line resource description.

    Examples:
        Read      → "src/models.py:10-50"
        Write     → "src/new_file.py"
        Edit      → "src/models.py"
        Bash      → "npm test" (truncated to 60 chars)
        Glob      → "**/*.py in src/"
        Grep      → "/pattern/ in *.ts"
        Agent     → "Explore: 'Find all test files...'"
        WebFetch  → "fetch: example.com"
        WebSearch → "search: 'query text'"
        mcp__*    → "mcp:server/tool(key_arg)"
    """
    # Normalize first
    tool_name = normalize_tool_name(tool_name)

    match tool_name:
        case "Read":
            path = _short_path(tool_input.get("file_path", "?"))
            offset = tool_input.get("offset")
            limit = tool_input.get("limit")
            if offset and limit:
                return f"{path}:{offset}-{offset + limit}"
            elif offset:
                return f"{path}:{offset}-"
            return path

        case "Write":
            return _short_path(tool_input.get("file_path", "?"))

        case "Edit":
            return _short_path(tool_input.get("file_path", "?"))

        case "Bash":
            cmd = tool_input.get("command", "?")
            return _truncate(cmd, 60)

        case "Glob":
            pattern = tool_input.get("pattern", "?")
            path = tool_input.get("path", "")
            if path:
                return f"{pattern} in {_short_path(path)}"
            return pattern

        case "Grep":
            pattern = tool_input.get("pattern", "?")
            glob = tool_input.get("glob", "")
            if glob:
                return f"/{_truncate(pattern, 30)}/ in {glob}"
            return f"/{_truncate(pattern, 40)}/"

        case "Agent":
            agent_type = tool_input.get("subagent_type", tool_input.get("type", "agent"))
            prompt = tool_input.get("prompt", "")
            bg = " [bg]" if tool_input.get("run_in_background") else ""
            return f"{agent_type}: '{_truncate(prompt, 45)}'{bg}"

        case "WebFetch":
            url = tool_input.get("url", "?")
            try:
                host = urlparse(url).hostname or url
            except Exception:
                host = url
            return f"fetch: {host}"

        case "WebSearch":
            query = tool_input.get("query", "?")
            return f"search: '{_truncate(query, 50)}'"

        case "LSP":
            command = tool_input.get("command", "?")
            path = tool_input.get("file_path", "")
            if path:
                return f"lsp:{command} {_short_path(path)}"
            return f"lsp:{command}"

        case "NotebookEdit":
            path = tool_input.get("notebook_path", "?")
            return f"notebook: {_short_path(path)}"

        case _:
            # MCP tools: mcp__server__tool
            if tool_name.startswith("mcp__"):
                return _extract_mcp_resource(tool_name, tool_input)
            return tool_name


def _extract_mcp_resource(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extract a readable summary from an MCP tool call."""
    parts = tool_name.split("__", 2)
    server = parts[1] if len(parts) > 1 else "?"
    tool = parts[2] if len(parts) > 2 else "?"
    key_arg = _first_string_arg(tool_input)
    if key_arg:
        return f"mcp:{server}/{tool}({_truncate(key_arg, 30)})"
    return f"mcp:{server}/{tool}"


def _short_path(path: str) -> str:
    """Shorten absolute paths to last 3 components."""
    if not path:
        return "?"
    parts = path.split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path


def _truncate(text: str, max_len: int) -> str:
    """Truncate with ellipsis, collapsing newlines."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _first_string_arg(d: dict[str, Any]) -> Optional[str]:
    """Return the first non-trivial string value from a dict."""
    for v in d.values():
        if isinstance(v, str) and len(v) > 2:
            return v
    return None
