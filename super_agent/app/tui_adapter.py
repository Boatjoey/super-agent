"""Historical terminal names for the agent application service.

The application service lives in :mod:`super_agent.app.agent_application`, because it
serves both front ends: the web interface drives the same object, and the
terminal is one of two front ends that read it. This module
keeps the old spellings — ``TerminalConversation``, ``new_terminal_conversation``,
``to_tui_*`` — working for callers and tests written before the split.

Nothing here is a second implementation. Every name is the same object.
"""

from __future__ import annotations

from super_agent.app.agent_application import (
    AgentApplication as TerminalConversation,
    new_agent_application as new_terminal_conversation,
    to_conversation_notification as to_conversation_notification,
    to_conversation_view as to_conversation_view,
    to_frontend_context_usage as to_tui_context_usage,
    to_frontend_message as to_tui_message,
    to_frontend_message_ptr as to_tui_message_ptr,
    to_frontend_permission as to_tui_permission,
    to_frontend_status as to_tui_status,
    to_frontend_tool_call as to_tui_tool_call,
)

__all__ = [
    "TerminalConversation",
    "new_terminal_conversation",
    "to_conversation_notification",
    "to_conversation_view",
    "to_tui_context_usage",
    "to_tui_message",
    "to_tui_message_ptr",
    "to_tui_permission",
    "to_tui_status",
    "to_tui_tool_call",
]
