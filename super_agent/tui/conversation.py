"""The boundary between the interactive CLI and the conversation runtime.

The contract itself is :mod:`super_agent.frontend` — the ports, the display DTOs,
the notification set, and the two concurrency primitives. This module re-exports
it under the names the terminal has always used, and adds the capabilities only
the terminal shows: the command ports, attachments, and MCP management.

Re-exporting rather than redefining is what makes the terminal one of three front
ends rather than the owner of the contract: a browser and an editor protocol read
the very same ``ConversationView`` and the very same notification kinds.

Two pieces exist for Python's concurrency model and are re-exported here:

* :class:`Channel` is a queue with an explicit close. ``asyncio.Queue`` cannot be
  closed, so the close is a flag and ``get`` returns ``None`` once the producer
  has closed and drained the buffer — which is what ends a listener command.
* :class:`Cancellation` is the cancel handle one turn is started with. It is a
  value, so a port that starts before the cancel still sees the cancel.
"""

from __future__ import annotations

from typing import Protocol

from super_agent.frontend import (
    ACCEPTED as ACCEPTED,
    APPROVE_ALWAYS as APPROVE_ALWAYS,
    APPROVE_ONCE as APPROVE_ONCE,
    CANCELLED as CANCELLED,
    CAPABILITIES as CAPABILITIES,
    DENY as DENY_APPROVAL,
    NOTIFICATION_KINDS as NOTIFICATION_KINDS,
    QUEUED as QUEUED,
    REJECTED as REJECTED,
    ROLE_ASSISTANT as ROLE_ASSISTANT,
    STEERING_HELD as STEERING_HELD,
    AgentStatus as AgentStatus,
    AgentStatusChanged as AgentStatusChanged,
    ApprovalReceipt as ApprovalReceipt,
    AttachmentSummary as AttachmentSummary,
    Cancellation as Cancellation,
    Channel as Channel,
    ConfigView as ConfigView,
    ContextUsage as ContextUsage,
    Conversation as ConversationPort,
    ConversationError as ConversationError,
    ConversationNotification as ConversationNotification,
    ConversationView as ConversationView,
    Decision as ApprovalDecision,
    Decision as Decision,
    Failure as Failure,
    Message as Message,
    MessageAppended as MessageAppended,
    PermissionRequest as PermissionRequest,
    ProviderPort as ProviderPort,
    ProviderView as ProviderView,
    QueuedInputAccepted as QueuedInputAccepted,
    QueuedInputWithdrawn as QueuedInputWithdrawn,
    QueuedReceipt as QueuedReceipt,
    Role as Role,
    SessionSummary as SessionSummary,
    SnapshotPort as SnapshotPort,
    SteeringAccepted as SteeringAccepted,
    SteeringReceipt as SteeringReceipt,
    SteeringWithdrawn as SteeringWithdrawn,
    StreamChunkReceived as StreamChunkReceived,
    ToolApprovalCleared as ToolApprovalCleared,
    ToolApprovalRequested as ToolApprovalRequested,
    ToolCall as ToolCall,
    TurnPort as TurnPort,
    UsageReported as UsageReported,
)
from super_agent.tui.attachments import Item as MessageAttachment, Port as AttachmentsPort
from super_agent.tui.commands import (
    AgentSummary,
    ExtensionPort,
    MCPPort,
    MCPServerSummary,
    MemoryPort,
    WorkspacePort,
)

__all__ = [
    "ACCEPTED",
    "APPROVE_ALWAYS",
    "APPROVE_ONCE",
    "CANCELLED",
    "CAPABILITIES",
    "DENY_APPROVAL",
    "NOTIFICATION_KINDS",
    "QUEUED",
    "REJECTED",
    "ROLE_ASSISTANT",
    "STEERING_HELD",
    "AgentStatus",
    "AgentStatusChanged",
    "AgentSummary",
    "ApprovalDecision",
    "ApprovalReceipt",
    "AttachmentSummary",
    "Cancellation",
    "Channel",
    "ConfigView",
    "ContextUsage",
    "Conversation",
    "ConversationError",
    "ConversationNotification",
    "ConversationView",
    "Decision",
    "Failure",
    "MCPServerSummary",
    "Message",
    "MessageAppended",
    "MessageAttachment",
    "PermissionRequest",
    "ProviderPort",
    "ProviderView",
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
    "QueuedReceipt",
    "Role",
    "SessionSummary",
    "SnapshotPort",
    "SteeringAccepted",
    "SteeringReceipt",
    "SteeringWithdrawn",
    "StreamChunkReceived",
    "ToolApprovalCleared",
    "ToolApprovalRequested",
    "ToolCall",
    "TurnPort",
    "UsageReported",
]


class Conversation(ConversationPort, Protocol):
    """The terminal bundle :func:`super_agent.tui.new` accepts.

    Both front ends now receive the same full contract; this name remains for the
    terminal's historical spelling. ``Protocol`` is listed explicitly so the
    bundle stays nominal rather than structural.
    """
