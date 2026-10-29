"""Pure conversion from runtime values to frontend contract values."""

import dataclasses

from super_agent import frontend
from super_agent.runtime.engine import EngineView
from super_agent.runtime.machine import (
    Message,
    State,
    ToolCall,
    state as states,
)
from super_agent.runtime.permission.types import Request as PermissionRequest
from super_agent.runtime.protocol.types import Usage
from super_agent.runtime.session import (
    MessageAppended,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    SessionError,
    SessionNotification,
    StateChanged,
    SteeringAccepted,
    SteeringWithdrawn,
    StreamChunkReceived,
    ToolApprovalCleared,
    ToolApprovalRequested,
    UsageReported,
)


def to_conversation_notification(
    notification: SessionNotification,
) -> frontend.ConversationNotification:
    """Map one runtime notification to the interface's own kind.

    An unknown kind becomes a :class:`frontend.ConversationError` naming its type.
    Dropping it would let a new runtime notification degrade the interface with
    nothing to show for it, which is the failure this default exists to prevent.
    """
    match notification:
        case StateChanged():
            return frontend.AgentStatusChanged(status=to_frontend_status(notification.state))
        case ToolApprovalRequested():
            return frontend.ToolApprovalRequested(
                tool_call=to_frontend_tool_call(notification.tool_call),
                request=to_frontend_permission(notification.request),
                batch_index=notification.batch_index,
                batch_total=notification.batch_total,
            )
        case ToolApprovalCleared():
            return frontend.ToolApprovalCleared()
        case StreamChunkReceived():
            return frontend.StreamChunkReceived(message=to_frontend_message_ptr(notification.message))
        case MessageAppended():
            return frontend.MessageAppended(message=to_frontend_message(notification.message))
        case UsageReported():
            return frontend.UsageReported(usage=to_frontend_context_usage(notification.usage))
        case SteeringAccepted():
            return frontend.SteeringAccepted(input_id=notification.input_id, step=notification.step)
        case SteeringWithdrawn():
            return frontend.SteeringWithdrawn(input_id=notification.input_id)
        case QueuedInputAccepted():
            return frontend.QueuedInputAccepted(input_id=notification.input_id, turn=notification.turn)
        case QueuedInputWithdrawn():
            return frontend.QueuedInputWithdrawn(input_id=notification.input_id)
        case SessionError():
            return frontend.ConversationError(
                failure=frontend.failure_from(notification.err, operation="run_turn") or frontend.Failure()
            )
        case _:
            return frontend.ConversationError(
                failure=frontend.Failure(
                    message=f"unknown runtime session notification: {type(notification).__name__}",
                    code=frontend.FAILED,
                    operation="run_turn",
                )
            )


def to_conversation_view(view: EngineView) -> frontend.ConversationView:
    """Map one engine snapshot to the view the transcript rebuilds from."""
    result = frontend.ConversationView(
        agent_status=to_frontend_status(view.state),
        messages=tuple(to_frontend_message(message) for message in view.messages),
        pending_tool_batch_index=view.pending_tool_batch_index,
        pending_tool_batch_total=view.pending_tool_batch_total,
        streaming_message=to_frontend_message_ptr(view.streaming_message),
    )
    if view.pending_tool is not None:
        result = dataclasses.replace(result, pending_tool=to_frontend_tool_call(view.pending_tool))
    if view.pending_permission is not None:
        result = dataclasses.replace(result, pending_permission=to_frontend_permission(view.pending_permission))
    return result


def to_frontend_context_usage(usage: Usage) -> frontend.ContextUsage:
    """One provider report, unchanged: the counts already mean the same thing."""
    return frontend.ContextUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def to_frontend_status(state: State) -> frontend.AgentStatus:
    """The presentation status for one runtime state.

    The table is exhaustive over the runtime states; a state it does not name is
    reported as ``Unknown`` rather than borrowing a neighbouring label.
    Presentation words, not runtime words, are the whole point: the CLI owns no
    runtime state enum.
    """
    match state:
        case states.STATE_INITIALIZING:
            return frontend.AgentStatus(label="Initializing", busy=True)
        case states.STATE_IDLE:
            return frontend.AgentStatus(label="Idle")
        case states.STATE_WAITING_LLM:
            return frontend.AgentStatus(label="WaitingLLM", busy=True)
        case states.STATE_WAITING_APPROVAL:
            return frontend.AgentStatus(label="WaitingApproval", awaiting_approval=True)
        case states.STATE_RUNNING_TOOL:
            return frontend.AgentStatus(label="RunningTool", busy=True)
        case states.STATE_ADVANCING_QUEUE:
            return frontend.AgentStatus(label="AdvancingQueue", busy=True)
        case _:
            return frontend.AgentStatus(label="Unknown")


def to_frontend_message_ptr(message: Message | None) -> frontend.Message | None:
    """A message as a presentation value, or ``None`` for no message."""
    if message is None:
        return None
    return to_frontend_message(message)


def to_frontend_message(message: Message) -> frontend.Message:
    """One message in the transcript's vocabulary.

    The runtime type is a flat tuple with no nil entries, so there is nothing to
    skip.
    """
    calls = tuple(to_frontend_tool_call(call) for call in message.tool_calls or ())
    attachments = tuple(
        frontend.Attachment(name=attachment.name, mime=attachment.mime) for attachment in message.attachments
    )
    return frontend.Message(
        role=frontend.Role(str(message.role)),
        content=message.content,
        reasoning_content=message.reasoning_content,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        tool_calls=calls,
        interrupted=message.interrupted,
        attachments=attachments,
    )


def to_frontend_tool_call(call: ToolCall) -> frontend.ToolCall:
    """One tool call, unchanged: the fields already mean the same thing."""
    return frontend.ToolCall(id=call.id, name=call.name, input=call.input)


def to_frontend_permission(request: PermissionRequest) -> frontend.PermissionRequest:
    """One permission request, with its sequences copied."""
    return frontend.PermissionRequest(
        tool_name=request.tool_name,
        command=request.command,
        command_class=str(request.command_class),
        cwd=request.cwd,
        touched_paths=tuple(request.touched_paths),
        env_vars=tuple(request.env_vars),
        reason=request.reason,
    )
