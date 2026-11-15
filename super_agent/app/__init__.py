"""Public composition entry points.

app.session assembles application use cases and concrete adapters. Local
configuration and infrastructure bridges live alongside it; application business
flows live in super_agent.application, and callers import application names from
there rather than through this package.
"""

from __future__ import annotations

# --- agents and servers ------------------------------------------------------
from super_agent.app.agents import AgentController as AgentController
from super_agent.app.config import (
    AgentSettings as AgentSettings,
    Config as Config,
    Flags as Flags,
    LSPServerSettings as LSPServerSettings,
    MemorySettings as MemorySettings,
    PermissionSettings as PermissionSettings,
    SandboxSettings as SandboxSettings,
    Settings as Settings,
    TelemetrySettings as TelemetrySettings,
    TerminalSettings as TerminalSettings,
    default_settings as default_settings,
    load_config as load_config,
    load_settings as load_settings,
    load_settings_file as load_settings_file,
    save_settings_file as save_settings_file,
    settings_path as settings_path,
)
from super_agent.app.extensions import (
    ExtensionSettings as ExtensionSettings,
    PluginManifest as PluginManifest,
)
from super_agent.app.instructions import load_project_instructions as load_project_instructions
from super_agent.app.mcp import (
    MCPController as MCPController,
    new_mcp_controller as new_mcp_controller,
)
from super_agent.app.memory import (
    MemoryController as MemoryController,
    open_memory as open_memory,
)

# --- the session constructors ------------------------------------------------
#
# Imported last: ``session`` reaches every other module here, so importing it
# after its dependencies keeps the chain readable top to bottom.
from super_agent.app.session import (
    new_session as new_session,
    new_session_with_extensions as new_session_with_extensions,
    new_session_with_mcp as new_session_with_mcp,
    wait_pending_closers as wait_pending_closers,
)
from super_agent.app.system_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT

__all__ = [
    "SYSTEM_PROMPT",
    "AgentController",
    "AgentSettings",
    "Config",
    "ExtensionSettings",
    "Flags",
    "LSPServerSettings",
    "MCPController",
    "MemoryController",
    "MemorySettings",
    "PermissionSettings",
    "PluginManifest",
    "SandboxSettings",
    "Settings",
    "TelemetrySettings",
    "TerminalSettings",
    "default_settings",
    "load_config",
    "load_project_instructions",
    "load_settings",
    "load_settings_file",
    "new_mcp_controller",
    "new_session",
    "new_session_with_extensions",
    "new_session_with_mcp",
    "save_settings_file",
    "settings_path",
    "wait_pending_closers",
]
