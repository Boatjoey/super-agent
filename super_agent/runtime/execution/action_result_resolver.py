"""Map completed action facts to machine events without consulting machine state."""

from __future__ import annotations

import dataclasses
from typing import Protocol

from super_agent.runtime.execution.policy import ToolDecision
from super_agent.runtime.execution.scheduled_action_result import (
    ApprovalReceived,
    ModelReplied,
    PermissionChecked,
    ScheduledActionResult,
    ToolFinished,
)
from super_agent.runtime.machine.approval import (
    APPROVE_ALWAYS,
    APPROVE_ONCE,
    DENY_APPROVAL,
    ApprovalDecision,
)
from super_agent.runtime.machine.event import (
    ApprovalAlwaysGranted,
    ApprovalDenied,
    ApprovalGranted,
    AssistantMessageReceived,
    Event,
    ToolBatchReceived,
    ToolCallDenied,
    ToolCallNeedsApproval,
    ToolCallReadyToRun,
    ToolResultReceived,
)
from super_agent.runtime.protocol.types import ToolSpec


@dataclasses.dataclass(frozen=True, slots=True)
class ActionResultInput:
    """Model capabilities needed to validate a model reply."""

    tool_specs: tuple[ToolSpec, ...] = ()


class ActionResultResolver(Protocol):
    """Turns an action result into a machine event."""

    def resolve(self, result: ScheduledActionResult, input: ActionResultInput) -> Event: ...


class DefaultActionResultResolver:
    """The only resolver; the port exists so tests can substitute one."""

    __slots__ = ()

    def resolve(self, result: ScheduledActionResult, input: ActionResultInput) -> Event:
        if isinstance(result, ModelReplied):
            return self._resolve_model_reply(result, input)
        if isinstance(result, ToolFinished):
            return ToolResultReceived(call=result.call, result=result.result)
        if isinstance(result, PermissionChecked):
            if result.decision == ToolDecision.DECISION_DENIED:
                return ToolCallDenied(call=result.call, reason=result.request.reason)
            if result.decision == ToolDecision.DECISION_RUN_DIRECTLY:
                return ToolCallReadyToRun(call=result.call)
            if result.decision == ToolDecision.DECISION_NEEDS_APPROVAL:
                return ToolCallNeedsApproval(call=result.call, request=result.request)
            raise ValueError("unknown permission decision")
        if isinstance(result, ApprovalReceived):
            return self._resolve_approval(result)
        raise ValueError(f"unknown action result type: {type(result).__name__}")

    def _resolve_model_reply(self, result: ModelReplied, input: ActionResultInput) -> Event:
        if not result.response.tool_calls:
            return AssistantMessageReceived(response=result.response)
        if not input.tool_specs:
            # A model that asks for tools when none are advertised would produce a
            # transcript with an unanswered tool call, which the provider rejects.
            # Failing here answers the turn with an error instead.
            raise ValueError("model returned tool call while tools are disabled")
        return ToolBatchReceived(
            content=result.response.content,
            calls=result.response.tool_calls,
            reasoning_content=result.response.reasoning_content,
        )

    def _resolve_approval(self, result: ApprovalReceived) -> Event:
        decision: ApprovalDecision = result.decision
        if decision == APPROVE_ONCE:
            return ApprovalGranted(call=result.call)
        if decision == APPROVE_ALWAYS:
            return ApprovalAlwaysGranted(call=result.call)
        if decision == DENY_APPROVAL:
            return ApprovalDenied(call=result.call)
        raise ValueError("unknown approval decision")
