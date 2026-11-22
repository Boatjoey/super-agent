"""The slash-command feature.

The package surface, re-exported so callers keep writing ``commands.Outcome`` and
``commands.is_command``. ``Command`` stays the palette entry; the effect type a
handler returns stays inside ``commands/model.py``.
"""

from __future__ import annotations

from super_agent.tui.commands.catalog import (
    Command as Command,
    is_command as is_command,
)
from super_agent.tui.commands.format import (
    divider as divider,
    format_instructions as format_instructions,
    format_mcp_servers as format_mcp_servers,
    format_named_items as format_named_items,
    format_permissions as format_permissions,
    format_sessions as format_sessions,
)
from super_agent.tui.commands.model import (
    Config as Config,
    Input as Input,
    Model as Model,
    new as new,
)
from super_agent.tui.commands.outcome import (
    CompactDone as CompactDone,
    MCPDone as MCPDone,
    Outcome as Outcome,
    StatusBar as StatusBar,
)
from super_agent.tui.commands.ports import (
    AgentPort as AgentPort,
    AgentSummary as AgentSummary,
    Attachment as Attachment,
    ExtensionPort as ExtensionPort,
    MCPPort as MCPPort,
    MCPServerSummary as MCPServerSummary,
    MemoryPort as MemoryPort,
    PermissionPort as PermissionPort,
    Ports as Ports,
    SessionPort as SessionPort,
    SessionSummary as SessionSummary,
    WorkspacePort as WorkspacePort,
)

__all__ = [
    "AgentPort",
    "AgentSummary",
    "Attachment",
    "Command",
    "CompactDone",
    "Config",
    "ExtensionPort",
    "Input",
    "MCPDone",
    "MCPPort",
    "MCPServerSummary",
    "MemoryPort",
    "Model",
    "Outcome",
    "PermissionPort",
    "Ports",
    "SessionPort",
    "SessionSummary",
    "StatusBar",
    "WorkspacePort",
    "divider",
    "format_instructions",
    "format_mcp_servers",
    "format_named_items",
    "format_permissions",
    "format_sessions",
    "is_command",
    "new",
]
