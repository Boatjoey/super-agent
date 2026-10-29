"""Shared frontend contracts re-exported for the interactive CLI.

The contract itself is :mod:`super_agent.frontend` — the ports, the display DTOs,
the notification set, and the two concurrency primitives. This module re-exports
the shared types and the terminal display aliases. Both front ends use the
same complete contract, including command ports, attachments and MCP management.

Re-exporting rather than redefining is what makes the terminal one of two front
ends rather than the owner of the contract: the web adapter reads
the very same ``ConversationView`` and the very same notification kinds.

Two pieces exist for Python's concurrency model and are re-exported here:

* :class:`Channel` is a queue with an explicit close. ``asyncio.Queue`` cannot be
  closed, so the close is a flag and ``get`` returns ``None`` once the producer
  has closed and drained the buffer — which is what ends a listener command.
* :class:`Cancellation` is the cancel handle one turn is started with. It is a
  value, so a port that starts before the cancel still sees the cancel.
"""

from __future__ import annotations

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
    ConversationError as ConversationError,
    ConversationNotification as ConversationNotification,
    ConversationView as ConversationView,
    Decision as ApprovalDecision,
    Decision as Decision,
    Failure as Failure,
    FrontendPorts as FrontendPorts,
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
from super_agent.tui.attachments import Item as MessageAttachment
from super_agent.tui.commands import (
    AgentSummary,
    MCPServerSummary,
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
    "ConversationError",
    "ConversationNotification",
    "ConversationView",
    "Decision",
    "Failure",
    "FrontendPorts",
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
