"""Public composition entry points and compatibility exports.

app.session assembles application use cases and concrete adapters. Local
configuration and infrastructure bridges live alongside it; application business
flows live in super_agent.application.
"""

from __future__ import annotations

# --- shared agent application service ---------------------------
#
# Imported under both names: ``AgentApplication`` is what the entry points
# build, and ``TerminalConversation`` is the spelling the terminal and its tests
# have always used. They are one class.
from super_agent.app.agent_application import (
    AgentApplication as AgentApplication,
    new_agent_application as new_agent_application,
)

# --- agents, workflows, and servers -----------------------------------------
from super_agent.app.agents import (
    AgentController as AgentController,
    AgentProfile as AgentProfile,
)
from super_agent.app.config import (
    AgentSettings as AgentSettings,
    Config as Config,
    Flags as Flags,
    LSPServerSettings as LSPServerSettings,
    MCPServerSettings as MCPServerSettings,
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
    Extensions as Extensions,
    ExtensionSettings as ExtensionSettings,
    PluginManifest as PluginManifest,
)
from super_agent.app.instructions import load_project_instructions as load_project_instructions
from super_agent.app.mcp import (
    MCPController as MCPController,
    MCPServerSummary as MCPServerSummary,
    new_mcp_controller as new_mcp_controller,
)
from super_agent.app.memory import (
    MemoryController as MemoryController,
    openMemory as openMemory,
)

# --- the session constructors ------------------------------------------------
#
# Imported last: ``session`` reaches every other module here, so importing it
# after its dependencies keeps the chain readable top to bottom.
from super_agent.app.session import (
    new_session as new_session,
    new_session_with_extensions as new_session_with_extensions,
    new_session_with_mcp as new_session_with_mcp,
    waitPendingClosers as waitPendingClosers,
)
from super_agent.app.system_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT
from super_agent.app.tui_adapter import (
    TerminalConversation as TerminalConversation,
    new_terminal_conversation as new_terminal_conversation,
)
from super_agent.app.workflows import WorkflowController as WorkflowController

__all__ = [
    "SYSTEM_PROMPT",
    "AgentApplication",
    "AgentController",
    "AgentProfile",
    "AgentSettings",
    "Config",
    "ExtensionSettings",
    "Extensions",
    "Flags",
    "LSPServerSettings",
    "MCPController",
    "MCPServerSettings",
    "MCPServerSummary",
    "MemoryController",
    "MemorySettings",
    "PermissionSettings",
    "PluginManifest",
    "SandboxSettings",
    "Settings",
    "TelemetrySettings",
    "TerminalConversation",
    "TerminalSettings",
    "WorkflowController",
    "default_settings",
    "load_config",
    "load_project_instructions",
    "load_settings",
    "load_settings_file",
    "new_agent_application",
    "new_mcp_controller",
    "new_session",
    "new_session_with_extensions",
    "new_session_with_mcp",
    "new_terminal_conversation",
    "save_settings_file",
    "settings_path",
    "waitPendingClosers",
]
