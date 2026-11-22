"""The command feature's output formatting.

Everything here is a pure function from a port's answer to the text the user
reads in scrollback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from super_agent.tui.commands.model import Config
    from super_agent.tui.commands.ports import MCPServerSummary, SessionSummary

__all__ = [
    "divider",
    "format_instructions",
    "format_mcp_servers",
    "format_named_items",
    "format_permissions",
    "format_sessions",
]


def divider(label: str) -> str:
    """A ``── label ──`` separator for scrollback."""
    return "── " + label + " ──"


def format_sessions(summaries: list[SessionSummary]) -> str:
    """One row per saved session."""
    if not summaries:
        return "No saved sessions"
    lines: list[str] = []
    for summary in summaries:
        parent = f"  child-of:{summary.parent_id}" if summary.parent_id else ""
        lines.append(f"{summary.id}  {summary.title}  {summary.provider}/{summary.model}{parent}")
    return "\n".join(lines)


def format_mcp_servers(servers: list[MCPServerSummary]) -> str:
    """One row per configured MCP server."""
    if not servers:
        return "No MCP servers"
    lines: list[str] = []
    for server in servers:
        tools = ", ".join(server.tools) or "no tools"
        lines.append(f"{server.name}  {tools}")
    return "\n".join(lines)


def format_instructions(paths: tuple[str, ...]) -> str:
    """The instruction sources that were loaded, in load order."""
    if not paths:
        return "No instruction files loaded"
    return "Loaded instruction sources:\n" + "\n".join(f"- {path}" for path in paths)


def format_permissions(config: Config, mode: str, auto_approve: bool) -> str:
    """The runtime's own policy values, so the display cannot drift from them."""
    return (
        f"Permission mode: {mode or 'ask'}\n"
        f"Tools: {_on_off(not config.no_tools)}\n"
        f"Approval: {_on_off(auto_approve)}\n"
        f"CWD: {config.cwd}"
    )


def format_named_items(label: str, items: list[str]) -> str:
    """A titled bullet list, or the empty case."""
    if not items:
        return "No " + label.lower()
    return label + ":\n- " + "\n- ".join(items)


def _on_off(enabled: bool) -> str:
    return "on" if enabled else "off"
