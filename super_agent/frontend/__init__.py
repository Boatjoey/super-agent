"""The contract between the application and every front end.

This package is the driving side of the hexagon: the ports a front end calls, the
display values it reads, and the notification set it consumes. It has no
dependency on the runtime, on a transport, or on a particular front end — the
terminal, the web interface, and the ACP server all import this and nothing else
of each other.

Three front ends, one contract:

* :mod:`super_agent.tui` renders it in a terminal;
* :mod:`super_agent.web` carries it over HTTP and server-sent events;
* :mod:`super_agent.acp` carries it over JSON-RPC on stdio for editors.

Implementation is supplied by :mod:`super_agent.app.conversation_adapter`, which
is the only place runtime values are converted into these types.
"""

from __future__ import annotations

from super_agent.frontend.approval import (
    APPROVE_ALWAYS as APPROVE_ALWAYS,
    APPROVE_ONCE as APPROVE_ONCE,
    DENY as DENY,
    Decision as Decision,
)
from super_agent.frontend.failure import (
    CANCELLED as CANCELLED,
    FAILED as FAILED,
    REFUSED as REFUSED,
    Failure as Failure,
    failure_from as failure_from,
)
from super_agent.frontend.notifications import (
    NOTIFICATION_KINDS as NOTIFICATION_KINDS,
    AgentStatusChanged as AgentStatusChanged,
    ConversationError as ConversationError,
    ConversationNotification as ConversationNotification,
    MessageAppended as MessageAppended,
    QueuedInputAccepted as QueuedInputAccepted,
    QueuedInputWithdrawn as QueuedInputWithdrawn,
    SteeringAccepted as SteeringAccepted,
    SteeringWithdrawn as SteeringWithdrawn,
    StreamChunkReceived as StreamChunkReceived,
    ToolApprovalCleared as ToolApprovalCleared,
    ToolApprovalRequested as ToolApprovalRequested,
    UsageReported as UsageReported,
)
from super_agent.frontend.ports import (
    CAPABILITIES as CAPABILITIES,
    AgentPort as AgentPort,
    AgentSummary as AgentSummary,
    AttachmentSummary as AttachmentSummary,
    ConfigPort as ConfigPort,
    ConfigView as ConfigView,
    Conversation as Conversation,
    MCPServerSummary as MCPServerSummary,
    PermissionPort as PermissionPort,
    SessionPort as SessionPort,
    SessionSummary as SessionSummary,
    SnapshotPort as SnapshotPort,
    TurnPort as TurnPort,
)
from super_agent.frontend.transport import Cancellation as Cancellation, Channel as Channel
from super_agent.frontend.view import (
    ACCEPTED as ACCEPTED,
    QUEUED as QUEUED,
    REJECTED as REJECTED,
    ROLE_ASSISTANT as ROLE_ASSISTANT,
    ROLE_TOOL as ROLE_TOOL,
    ROLE_USER as ROLE_USER,
    STEERING_HELD as STEERING_HELD,
    AgentStatus as AgentStatus,
    ApprovalReceipt as ApprovalReceipt,
    Attachment as Attachment,
    ContextUsage as ContextUsage,
    ConversationView as ConversationView,
    Message as Message,
    PermissionRequest as PermissionRequest,
    QueuedReceipt as QueuedReceipt,
    Role as Role,
    SteeringReceipt as SteeringReceipt,
    ToolCall as ToolCall,
)

__all__ = [
    "ACCEPTED",
    "APPROVE_ALWAYS",
    "APPROVE_ONCE",
    "CANCELLED",
    "CAPABILITIES",
    "DENY",
    "FAILED",
    "NOTIFICATION_KINDS",
    "QUEUED",
    "REFUSED",
    "REJECTED",
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "STEERING_HELD",
    "AgentPort",
    "AgentStatus",
    "AgentStatusChanged",
    "AgentSummary",
    "ApprovalReceipt",
    "Attachment",
    "AttachmentSummary",
    "Cancellation",
    "Channel",
    "ConfigPort",
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
    "PermissionPort",
    "PermissionRequest",
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
    "QueuedReceipt",
    "Role",
    "SessionPort",
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
    "failure_from",
]
