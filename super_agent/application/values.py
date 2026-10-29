"""Application values shared with configuration adapters."""

import dataclasses

from super_agent.jsonutil import json_field
from super_agent.runtime.execution import ZERO_PERMISSION_MODE, PermissionMode


@dataclasses.dataclass(frozen=True, slots=True)
class AgentProfile:
    """One selectable agent: who it talks to, as what, and with which tools."""

    name: str = ""
    provider: str = ""
    model: str = ""
    prompt: str = ""
    permission_mode: PermissionMode = ZERO_PERMISSION_MODE
    tools: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class MCPServerSettings:
    """One entry of ``mcp_servers``."""

    command: str = dataclasses.field(default="", metadata=json_field(name="command"))
    args: tuple[str, ...] = dataclasses.field(default=(), metadata=json_field(name="args"))
    env: dict[str, str] = dataclasses.field(default_factory=dict[str, str], metadata=json_field(name="env"))
    cwd: str = dataclasses.field(default="", metadata=json_field(name="cwd"))
    connect_timeout_seconds: int = dataclasses.field(default=0, metadata=json_field(name="connect_timeout_seconds"))
    call_timeout_seconds: int = dataclasses.field(default=0, metadata=json_field(name="call_timeout_seconds"))


@dataclasses.dataclass(frozen=True, slots=True)
class Extensions:
    """Everything the extension roots and settings together provide."""

    commands: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    hooks: dict[str, tuple[str, ...]] = dataclasses.field(default_factory=dict[str, tuple[str, ...]])
    skill_prompt: str = ""
    skills: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()
