"""The contract's JSON projection, shared by the transports.

A browser and an editor protocol both need these values as plain JSON-able
mappings. Doing the projection once here, instead of once per transport, is what
keeps a server-sent event and an ACP ``session/update`` describing the same
conversation state in the same words.

Nothing here knows about HTTP, JSON-RPC, or the runtime: it is a pure function of
a DTO.
"""

from __future__ import annotations

from typing import Any

from super_agent.frontend.failure import Failure
from super_agent.frontend.notifications import (
    AgentStatusChanged,
    ConversationError,
    ConversationNotification,
    MessageAppended,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    SteeringAccepted,
    SteeringWithdrawn,
    StreamChunkReceived,
    ToolApprovalCleared,
    ToolApprovalRequested,
    UsageReported,
)
from super_agent.frontend.ports import AgentSummary, ConfigView
from super_agent.frontend.view import (
    AgentStatus,
    ApprovalReceipt,
    Attachment,
    ContextUsage,
    ConversationView,
    Message,
    PermissionRequest,
    QueuedReceipt,
    SteeringReceipt,
    ToolCall,
)

__all__ = [
    "agent_to_json",
    "attachment_to_json",
    "config_to_json",
    "error_text",
    "failure_to_json",
    "message_to_json",
    "notification_to_json",
    "permission_to_json",
    "receipt_to_json",
    "status_to_json",
    "tool_call_to_json",
    "usage_to_json",
    "view_to_json",
]


def attachment_to_json(attachment: Attachment) -> dict[str, Any]:
    return {"name": attachment.name, "mime": attachment.mime}


def tool_call_to_json(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "input": call.input}


def message_to_json(message: Message) -> dict[str, Any]:
    return {
        "role": str(message.role),
        "content": message.content,
        "reasoning_content": message.reasoning_content,
        "tool_call_id": message.tool_call_id,
        "tool_name": message.tool_name,
        "tool_calls": [tool_call_to_json(call) for call in message.tool_calls],
        "interrupted": message.interrupted,
        "attachments": [attachment_to_json(item) for item in message.attachments],
    }


def status_to_json(status: AgentStatus) -> dict[str, Any]:
    return {"label": status.label, "busy": status.busy, "awaiting_approval": status.awaiting_approval}


def permission_to_json(request: PermissionRequest) -> dict[str, Any]:
    return {
        "tool_name": request.tool_name,
        "command": request.command,
        "command_class": request.command_class,
        "cwd": request.cwd,
        "touched_paths": list(request.touched_paths),
        "env_vars": list(request.env_vars),
        "reason": request.reason,
    }


def usage_to_json(usage: ContextUsage) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def receipt_to_json(receipt: SteeringReceipt | QueuedReceipt | ApprovalReceipt) -> dict[str, Any]:
    """One receipt, naming whatever it is a receipt for.

    Steering and queued receipts answer for an input, an approval receipt for a
    request; sending both keys would invite a front end to read the wrong one.
    """
    if isinstance(receipt, ApprovalReceipt):
        return {"request_id": receipt.request_id, "status": receipt.status, "reason": receipt.reason}
    return {"input_id": receipt.input_id, "status": receipt.status, "reason": receipt.reason}


def error_text(error: BaseException | None) -> str:
    """An unexpected exception as one displayable sentence.

    This is for the transport's last-resort handler, where something raised that no
    port promised to report as a value. Application results travel as
    :class:`~super_agent.frontend.failure.Failure` instead.
    """
    if error is None:
        return ""
    text = str(error)
    return text if text else type(error).__name__


def failure_to_json(failure: Failure | None) -> dict[str, Any] | None:
    """A failure as a displayable payload. ``None`` stays ``None``.

    An object of empty strings would look like a failure whose message got lost,
    and every front end would have to test four fields to find out it was fine.
    """
    if failure is None:
        return None
    return {
        "message": failure.message,
        "code": failure.code,
        "operation": failure.operation,
        "request_id": failure.request_id,
    }


def agent_to_json(agent: AgentSummary) -> dict[str, Any]:
    return {
        "name": agent.name,
        "provider": agent.provider,
        "model": agent.model,
        "permission_mode": agent.permission_mode,
    }


def config_to_json(config: ConfigView) -> dict[str, Any]:
    return {
        "session_id": config.session_id,
        "session_title": config.session_title,
        "workspace": config.workspace,
        "roots": list(config.roots),
        "agent": config.agent,
        "provider": config.provider,
        "model": config.model,
        "permission_mode": config.permission_mode,
        "auto_approve": config.auto_approve,
        "reasoning_effort": config.reasoning_effort,
        "reasoning_efforts": list(config.reasoning_efforts),
        "agents": [agent_to_json(agent) for agent in config.agents],
        "memory_enabled": config.memory_enabled,
        "memory_backend": config.memory_backend,
        "capabilities": list(config.capabilities),
    }


def view_to_json(view: ConversationView) -> dict[str, Any]:
    return {
        "agent_status": status_to_json(view.agent_status),
        "messages": [message_to_json(message) for message in view.messages],
        "pending_tool": None if view.pending_tool is None else tool_call_to_json(view.pending_tool),
        "pending_permission": None if view.pending_permission is None else permission_to_json(view.pending_permission),
        "pending_tool_batch_index": view.pending_tool_batch_index,
        "pending_tool_batch_total": view.pending_tool_batch_total,
        "pending_approval_id": view.pending_approval_id,
        "streaming_message": None if view.streaming_message is None else message_to_json(view.streaming_message),
    }


def notification_to_json(notification: ConversationNotification) -> dict[str, Any]:
    """One notification, tagged with its kind.

    The mapping is exhaustive over the sealed set; the fallback exists so a kind
    added later is still sent with its own name rather than silently becoming
    something else.
    """
    match notification:
        case AgentStatusChanged():
            return {"kind": notification.kind, "status": status_to_json(notification.status)}
        case ToolApprovalRequested():
            return {
                "kind": notification.kind,
                "tool_call": tool_call_to_json(notification.tool_call),
                "request": permission_to_json(notification.request),
                "request_id": notification.request_id,
                "batch_index": notification.batch_index,
                "batch_total": notification.batch_total,
            }
        case ToolApprovalCleared():
            return {"kind": notification.kind, "request_id": notification.request_id}
        case StreamChunkReceived():
            return {
                "kind": notification.kind,
                "message": None if notification.message is None else message_to_json(notification.message),
            }
        case MessageAppended():
            return {"kind": notification.kind, "message": message_to_json(notification.message)}
        case SteeringAccepted():
            return {"kind": notification.kind, "input_id": notification.input_id, "step": notification.step}
        case SteeringWithdrawn():
            return {"kind": notification.kind, "input_id": notification.input_id}
        case QueuedInputAccepted():
            return {"kind": notification.kind, "input_id": notification.input_id, "turn": notification.turn}
        case QueuedInputWithdrawn():
            return {"kind": notification.kind, "input_id": notification.input_id}
        case UsageReported():
            return {"kind": notification.kind, "usage": usage_to_json(notification.usage)}
        case ConversationError():
            return {"kind": notification.kind, "failure": failure_to_json(notification.failure)}
        case _:
            return {"kind": "UnknownNotification", "type": type(notification).__name__}
