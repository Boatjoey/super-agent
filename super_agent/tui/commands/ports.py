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
from typing import Protocol

from super_agent.frontend.ports import (
    AgentPort as AgentPort,
    AgentSummary as AgentSummary,
    AttachmentSummary as Attachment,
    MCPServerSummary as MCPServerSummary,
    PermissionPort as PermissionPort,
    ProviderPort as ProviderPort,
    ProviderView as ProviderView,
    SessionPort as SessionPort,
    SessionSummary as SessionSummary,
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


class MCPPort(Protocol):
    """Manages MCP server lifecycle."""

    def list_mcp_servers(self) -> list[MCPServerSummary]: ...

    async def add_mcp_server(self, name: str, command: str, args: list[str]) -> None: ...

    async def remove_mcp_server(self, name: str) -> None: ...

    async def restart_mcp_server(self, name: str) -> None: ...


class MemoryPort(Protocol):
    """Reads and writes cross-session memory, and switches it on or off."""

    async def memories(self) -> list[str]: ...

    async def remember(self, text: str) -> None: ...

    async def forget_memories(self) -> None: ...

    def memory_enabled(self) -> bool: ...

    def memory_backend(self) -> str: ...

    async def set_memory_enabled(self, enabled: bool) -> None: ...


class WorkspacePort(Protocol):
    """Runs read-only repository and language-server queries."""

    async def git_diff(self) -> str: ...

    async def git_status(self) -> str: ...

    async def diagnostics(self, path: str) -> str: ...


class ExtensionPort(Protocol):
    """Exposes discovered commands, skills, and plugins."""

    def custom_commands(self) -> list[str]: ...

    async def expand_custom_command(self, name: str, arguments: str) -> str: ...

    def skills(self) -> list[str]: ...

    def plugins(self) -> list[str]: ...
