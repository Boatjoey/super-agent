"""The narrow ports the command feature needs, one per use case.

Each port is declared here and implemented at the composition boundary; the
feature never learns what is behind it. Reads are synchronous, and every call
that can touch the disk, the network, or another process is ``async``: it is
awaited rather than run inline.

The conversation-lifecycle, permission, agent, and summary types are the shared
front-end contract's (``super_agent.frontend``) and are re-exported here: a
browser and an editor show the same saved-session list and the same profile
summary, so the shape may not be the terminal's own. What stays in this module is
what only the terminal's command palette offers — MCP server management, memory,
repository queries, and extensions.
"""

from __future__ import annotations

import dataclasses

from super_agent.frontend.ports import (
    AgentPort as AgentPort,
    AgentSummary as AgentSummary,
    AttachmentSummary as Attachment,
    ExtensionPort as ExtensionPort,
    MCPServerSummary as MCPServerSummary,
    MCPPort as MCPPort,
    MemoryPort as MemoryPort,
    PermissionPort as PermissionPort,
    ProviderPort as ProviderPort,
    ProviderView as ProviderView,
    SessionPort as SessionPort,
    SessionSummary as SessionSummary,
    WorkspacePort as WorkspacePort,
)

__all__ = [
    "AgentPort",
    "AgentSummary",
    "Attachment",
    "ExtensionPort",
    "MCPPort",
    "MCPServerSummary",
    "MemoryPort",
    "PermissionPort",
    "Ports",
    "ProviderPort",
    "ProviderView",
    "SessionPort",
    "SessionSummary",
    "WorkspacePort",
]


@dataclasses.dataclass(frozen=True, slots=True)
class Ports:
    """Every capability the command feature needs."""

    sessions: SessionPort
    permissions: PermissionPort
    mcp: MCPPort
    agents: AgentPort
    memory: MemoryPort
    workspace: WorkspacePort
    extensions: ExtensionPort
    providers: ProviderPort
