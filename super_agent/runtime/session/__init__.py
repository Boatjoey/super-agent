"""Application use cases over the engine, and the ports they reach through.

The session owns no terminal behaviour and no scheduling: it supplies an approval
waiter, a streaming callback, a per-turn state observer, and the durability that
makes each of them survive a restart. R5 in
``tests/architecture/test_dependencies.py`` keeps this layer off ``os``,
``pathlib``, ``store``, and ``tui``.

A package spans several modules here, so this module stands in for the package
namespace.
"""

from __future__ import annotations

from super_agent.runtime.session.attachments import (
    AttachmentReader as AttachmentReader,
)
from super_agent.runtime.session.checkpoint import (
    CheckpointMixin as CheckpointMixin,
    checkpoint_paths as checkpoint_paths,
)
from super_agent.runtime.session.export import (
    ExportMixin as ExportMixin,
    ExportWriter as ExportWriter,
    html_export as html_export,
    markdown_export as markdown_export,
)
from super_agent.runtime.session.history import (
    HistoryMixin as HistoryMixin,
    compacted_messages as compacted_messages,
    non_system_message_count as non_system_message_count,
    saved_workspace_spec as saved_workspace_spec,
)
from super_agent.runtime.session.memory import (
    MEMORY_SYSTEM_PREFIX as MEMORY_SYSTEM_PREFIX,
    Memory as Memory,
    MemoryDisabledError as MemoryDisabledError,
    OffMemory as OffMemory,
    Switch as Switch,
    with_memory_context as with_memory_context,
)
from super_agent.runtime.session.notifications import (
    NOTIFICATIONS_CLOSED as NOTIFICATIONS_CLOSED,
    MessageAppended as MessageAppended,
    NotificationsClosed as NotificationsClosed,
    QueuedInputAccepted as QueuedInputAccepted,
    QueuedInputWithdrawn as QueuedInputWithdrawn,
    SessionError as SessionError,
    SessionNotification as SessionNotification,
    StateChanged as StateChanged,
    SteeringAccepted as SteeringAccepted,
    SteeringWithdrawn as SteeringWithdrawn,
    StreamChunkReceived as StreamChunkReceived,
    ToolApprovalCleared as ToolApprovalCleared,
    ToolApprovalRequested as ToolApprovalRequested,
    UsageReported as UsageReported,
)
from super_agent.runtime.session.persistence import (
    ErrorPersistenceError as ErrorPersistenceError,
    PersistenceMixin as PersistenceMixin,
)
from super_agent.runtime.session.repository import (
    WORKSPACE_ACCESS_READ as WORKSPACE_ACCESS_READ,
    WORKSPACE_ACCESS_READ_WRITE as WORKSPACE_ACCESS_READ_WRITE,
    AuditEvent as AuditEvent,
    FileSnapshot as FileSnapshot,
    Metadata as Metadata,
    Repository as Repository,
    SessionID as SessionID,
    Summary as Summary,
    Workspace as Workspace,
    WorkspaceAccessMode as WorkspaceAccessMode,
    WorkspaceRootSpec as WorkspaceRootSpec,
    WorkspaceSpec as WorkspaceSpec,
    workspace_spec_pointer as workspace_spec_pointer,
)
from super_agent.runtime.session.session import (
    Closer as Closer,
    Session as Session,
    SessionBase as SessionBase,
    create_persistent_session as create_persistent_session,
    new_persistent_session as new_persistent_session,
    new_session as new_session,
)
from super_agent.runtime.session.snapshot_emitter import (
    SnapshotEmitter as SnapshotEmitter,
    permission_request as permission_request,
)
from super_agent.runtime.session.turn import (
    APPROVALS_CLOSED as APPROVALS_CLOSED,
    ApprovalsClosed as ApprovalsClosed,
    TurnMixin as TurnMixin,
    wait_approval as wait_approval,
)

__all__ = [
    "APPROVALS_CLOSED",
    "MEMORY_SYSTEM_PREFIX",
    "NOTIFICATIONS_CLOSED",
    "WORKSPACE_ACCESS_READ",
    "WORKSPACE_ACCESS_READ_WRITE",
    "ApprovalsClosed",
    "AttachmentReader",
    "AuditEvent",
    "CheckpointMixin",
    "Closer",
    "ErrorPersistenceError",
    "ExportMixin",
    "ExportWriter",
    "FileSnapshot",
    "HistoryMixin",
    "Memory",
    "MemoryDisabledError",
    "MessageAppended",
    "Metadata",
    "NotificationsClosed",
    "OffMemory",
    "PersistenceMixin",
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
    "Repository",
    "Session",
    "SessionBase",
    "SessionError",
    "SessionID",
    "SessionNotification",
    "SnapshotEmitter",
    "StateChanged",
    "SteeringAccepted",
    "SteeringWithdrawn",
    "StreamChunkReceived",
    "Summary",
    "Switch",
    "ToolApprovalCleared",
    "ToolApprovalRequested",
    "TurnMixin",
    "UsageReported",
    "Workspace",
    "WorkspaceAccessMode",
    "WorkspaceRootSpec",
    "WorkspaceSpec",
    "checkpoint_paths",
    "compacted_messages",
    "create_persistent_session",
    "html_export",
    "markdown_export",
    "new_persistent_session",
    "new_session",
    "non_system_message_count",
    "permission_request",
    "saved_workspace_spec",
    "wait_approval",
    "with_memory_context",
    "workspace_spec_pointer",
]
