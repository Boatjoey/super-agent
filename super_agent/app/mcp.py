"""MCP process, tool catalog and settings infrastructure.

Application transactions live in application.mcp; this module implements their
individual outbound operations and the compatibility constructor.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping, Sequence

from super_agent import tools
from super_agent.app.config import MCPServerSettings, load_settings_file, save_settings_file
from super_agent.application.mcp import MCPController as ApplicationMCPController, MCPServerSummary as MCPServerSummary
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import ToolRunner
from super_agent.tools import mcp as mcptools

__all__ = [
    "MCPController",
    "MCPServerSummary",
    "cloneMCPSettings",
    "new_mcp_controller",
    "toolNames",
]


class MCPBackendAdapter:
    def __init__(self, manager: mcptools.Manager, registry: tools.Registry, settingsPath: str, workspace: str) -> None:
        self.manager = manager
        self.registry = registry
        self.settingsPath = settingsPath
        self.workspace = workspace

    def servers(self) -> list[MCPServerSummary]:
        return [MCPServerSummary(name=server.name, tools=tuple(server.tools)) for server in self.manager.servers()]

    async def connect(self, ctx: RunContext, name: str, settings: MCPServerSettings) -> Sequence[ToolRunner]:
        return await self.manager.add(ctx, self.serverConfig(name, settings))

    async def disconnect(self, name: str) -> Sequence[str]:
        return await self.manager.remove(name)

    def install(self, items: Sequence[ToolRunner]) -> None:
        self.registry.add(*items)

    def uninstall(self, names: Sequence[str]) -> None:
        self.registry.remove(*names)

    async def restart(self, ctx: RunContext, name: str) -> None:
        await self.manager.restart(ctx, name, lambda old, replacement: self.registry.replace(old, *replacement))

    def save(self, name: str, server: MCPServerSettings | None) -> None:
        self.persist(name, server)

    def persist(self, name: str, server: MCPServerSettings | None) -> None:
        """Write one server's settings, or forget it, without touching the rest."""
        settings = load_settings_file(self.settingsPath)
        servers = dict(settings.mcp_servers)
        if server is None:
            servers.pop(name, None)
        else:
            servers[name] = server
        save_settings_file(self.settingsPath, dataclasses.replace(settings, mcp_servers=servers))

    def serverConfig(self, name: str, settings: MCPServerSettings) -> mcptools.ServerConfig:
        """The connect-time configuration for one server, with its cwd resolved."""
        cwd = settings.cwd
        if cwd == "":
            cwd = self.workspace
        elif not os.path.isabs(cwd):
            cwd = os.path.join(self.workspace, cwd)
        return mcptools.ServerConfig(
            name=name,
            command=settings.command,
            args=list(settings.args),
            env=dict(settings.env),
            cwd=cwd,
            connect_timeout=float(settings.connect_timeout_seconds),
            call_timeout=float(settings.call_timeout_seconds),
        )


class MCPController(ApplicationMCPController):
    """Compatibility constructor that injects MCP and settings infrastructure."""

    def __init__(
        self,
        manager: mcptools.Manager,
        registry: tools.Registry,
        settingsPath: str,
        workspace: str,
        configs: Mapping[str, MCPServerSettings] | None,
    ) -> None:
        super().__init__(MCPBackendAdapter(manager, registry, settingsPath, workspace), configs)


def new_mcp_controller(
    manager: mcptools.Manager,
    registry: tools.Registry,
    settingsPath: str,
    workspace: str,
    configs: Mapping[str, MCPServerSettings] | None,
) -> MCPController:
    """The controller over ``manager``."""
    return MCPController(manager, registry, settingsPath, workspace, configs)


def cloneMCPSettings(configs: Mapping[str, MCPServerSettings] | None) -> dict[str, MCPServerSettings]:
    """A mutable copy, so the controller never writes through a caller's map."""
    return {} if configs is None else dict(configs)


def toolNames(items: Sequence[mcptools.RemoteTool]) -> list[str]:
    """The spec names a batch of discovered tools registers under."""
    names: list[str] = []
    for item in items:
        specs = item.specs()
        if specs:
            names.append(specs[0].name)
    return names
