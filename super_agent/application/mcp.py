"""MCP management transactions and compensation."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping, Sequence

from super_agent.application.ports import MCPBackend
from super_agent.application.values import MCPServerSettings
from super_agent.errors import JoinedError
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.protocol.types import ToolRunner


@dataclasses.dataclass(frozen=True, slots=True)
class MCPServerSummary:
    """One configured server and the tools it contributed."""

    name: str = ""
    tools: tuple[str, ...] = ()


class MCPController:
    def __init__(self, backend: MCPBackend, configs: Mapping[str, MCPServerSettings] | None) -> None:
        self.backend = backend
        self.configs = {} if configs is None else dict(configs)
        self._lock = asyncio.Lock()

    def list(self) -> list[MCPServerSummary]:
        """Every connected server, ordered by name."""
        return [MCPServerSummary(name=server.name, tools=tuple(server.tools)) for server in self.backend.servers()]

    async def add(self, ctx: RunContext, name: str, command: str, args: Sequence[str]) -> None:
        """Connect a server, install its tools, and persist it."""
        async with self._lock:
            if name == "" or command == "":
                raise ValueError("MCP server name and command are required")
            settings = MCPServerSettings(command=command, args=tuple(args))
            added = await self.backend.connect(ctx, name, settings)
            try:
                self.backend.install(added)
            except BaseException:
                await self.backend.disconnect(name)
                raise
            try:
                self.backend.save(name, settings)
            except BaseException:
                self.backend.uninstall(toolNames(added))
                await self.backend.disconnect(name)
                raise
            self.configs[name] = settings

    async def remove(self, name: str) -> None:
        """Disconnect a server, drop its tools, and forget it in settings.

        A persistence failure reconnects the server rather than leaving the
        session without one settings.json says it has.
        """
        async with self._lock:
            settings = self.configs.get(name)
            if settings is None:
                raise ValueError("MCP server not found: " + name)
            names = await self.backend.disconnect(name)
            self.backend.uninstall(names)
            try:
                self.backend.save(name, None)
            except BaseException as error:
                reconnectError: BaseException | None = None
                try:
                    added = await self.backend.connect(live_context(), name, settings)
                    self.backend.install(added)
                except BaseException as failure:
                    reconnectError = failure
                raise JoinedError(error, reconnectError) from None
            del self.configs[name]

    async def restart(self, ctx: RunContext, name: str) -> None:
        """Reconnect a server, replacing its tools in the registry."""
        async with self._lock:
            await self.backend.restart(ctx, name)


def toolNames(items: Sequence[ToolRunner]) -> list[str]:
    return [specs[0].name for item in items if (specs := item.specs())]
