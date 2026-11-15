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
    checkpointPaths as checkpointPaths,
)
from super_agent.runtime.session.export import (
    ExportMixin as ExportMixin,
    ExportWriter as ExportWriter,
    htmlExport as htmlExport,
    markdownExport as markdownExport,
)
from super_agent.runtime.session.history import (
    HistoryMixin as HistoryMixin,
    compactedMessages as compactedMessages,
    nonSystemMessageCount as nonSystemMessageCount,
    savedWorkspaceSpec as savedWorkspaceSpec,
)
from super_agent.runtime.session.memory import (
    MEMORY_SYSTEM_PREFIX as MEMORY_SYSTEM_PREFIX,
    Memory as Memory,
    MemoryDisabled as MemoryDisabled,
    OffMemory as OffMemory,
    Switch as Switch,
    withMemoryContext as withMemoryContext,
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
    ErrorPersistenceFailed as ErrorPersistenceFailed,
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
    workspaceSpecPointer as workspaceSpecPointer,
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
    waitApproval as waitApproval,
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
    "ErrorPersistenceFailed",
    "ExportMixin",
    "ExportWriter",
    "FileSnapshot",
    "HistoryMixin",
    "Memory",
    "MemoryDisabled",
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
    "checkpointPaths",
    "compactedMessages",
    "create_persistent_session",
    "htmlExport",
    "markdownExport",
    "new_persistent_session",
    "new_session",
    "nonSystemMessageCount",
    "permission_request",
    "savedWorkspaceSpec",
    "waitApproval",
    "withMemoryContext",
    "workspaceSpecPointer",
]
