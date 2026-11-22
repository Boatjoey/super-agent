"""The transcript feature.

The package surface, re-exported so callers keep writing
``transcript.Model`` and ``transcript.ROLE_ASSISTANT``.
"""

from __future__ import annotations

from super_agent.tui.transcript.model import (
    ROLE_ASSISTANT as ROLE_ASSISTANT,
    ROLE_TOOL as ROLE_TOOL,
    ROLE_USER as ROLE_USER,
    Attachment as Attachment,
    Intent as Intent,
    MarkdownRenderer as MarkdownRenderer,
    Message as Message,
    Model as Model,
    Role as Role,
    Styles as Styles,
    ToolCall as ToolCall,
    ToolDisplayGroup as ToolDisplayGroup,
    default_styles as default_styles,
    extract_code_blocks as extract_code_blocks,
    new as new,
    tool_display as tool_display,
    tool_groups as tool_groups,
)

__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "Attachment",
    "Intent",
    "MarkdownRenderer",
    "Message",
    "Model",
    "Role",
    "Styles",
    "ToolCall",
    "ToolDisplayGroup",
    "default_styles",
    "extract_code_blocks",
    "new",
    "tool_display",
    "tool_groups",
]
