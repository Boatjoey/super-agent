"""The presentation values every front end reads.

These are the display DTOs the composition boundary hands a front end and the
values a front end keeps in its own state. They deliberately carry no runtime
enum, no provider object, and no transport concern, so a terminal, a browser, and
an editor protocol can all consume the same snapshot.

Three front ends share this module: the interactive CLI, the local web interface,
and the Agent Client Protocol server. They differ in how they render and how they
move bytes, never in what a conversation is.
"""

from __future__ import annotations

import dataclasses
from typing import Final

__all__ = [
    "ACCEPTED",
    "QUEUED",
    "REJECTED",
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "STEERING_HELD",
    "AgentStatus",
    "ApprovalReceipt",
    "Attachment",
    "ContextUsage",
    "ConversationView",
    "Message",
    "PermissionRequest",
    "QueuedReceipt",
    "Role",
    "SteeringReceipt",
    "ToolCall",
]


class Role(str):
    """Who produced one message."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Role({str.__repr__(self)})"


ROLE_USER: Final[Role] = Role("user")
ROLE_ASSISTANT: Final[Role] = Role("assistant")
ROLE_TOOL: Final[Role] = Role("tool")


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool call, exactly as the model emitted it."""

    id: str = ""
    name: str = ""
    input: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Attachment:
    """One file a message carries."""

    name: str = ""
    mime: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Message:
    """One transcript entry. Frozen, so a rendered transcript never mutates."""

    role: Role = ROLE_USER
    content: str = ""
    reasoning_content: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    interrupted: bool = False
    attachments: tuple[Attachment, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class AgentStatus:
    """What the agent is doing, in presentation words rather than runtime states."""

    label: str = "Idle"
    busy: bool = False
    awaiting_approval: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class PermissionRequest:
    """Why a tool call needs a decision, as a menu or a dialog shows it."""

    tool_name: str = ""
    command: str = ""
    command_class: str = ""
    cwd: str = ""
    touched_paths: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    reason: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class ContextUsage:
    """What the provider reported the latest model call cost in tokens.

    Absolute counts only: the runtime knows no context-window size, so a fraction
    or a remainder cannot be derived from these.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


#: Accepted, and held until the next step begins. The input is *not* part of the
#: conversation yet, so showing it as delivered would be a lie. The other two
#: states a submission can reach are reported later, as
#: :class:`~super_agent.frontend.notifications.SteeringAccepted` and
#: :class:`~super_agent.frontend.notifications.SteeringWithdrawn`.
STEERING_HELD: Final[str] = "held"
#: Accepted, and waiting for the next turn. Like ``held`` this is not delivery:
#: the turn that takes it up is reported later, as
#: :class:`~super_agent.frontend.notifications.QueuedInputAccepted`.
QUEUED: Final[str] = "queued"
#: Refused, by either kind of submission. The reason is for display, and the
#: input belongs to nobody — so nothing may be cleared or promised on the
#: strength of it having been sent.
REJECTED: Final[str] = "rejected"
#: The application took the approval and handed it to the runtime. Only a
#: matching, still-pending request can reach this state.
ACCEPTED: Final[str] = "accepted"


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringReceipt:
    """What became of one submitted in-turn input, answered immediately.

    Only ``held`` and ``rejected`` are possible here: acceptance happens later, at
    a step boundary, and arrives as a notification. ``input_id`` is the handle the
    later notification quotes, which is why the caller must not invent its own
    view of which input is which.
    """

    input_id: str = ""
    status: str = REJECTED
    reason: str = ""

    @classmethod
    def held(cls, input_id: str) -> SteeringReceipt:
        return cls(input_id=input_id, status=STEERING_HELD)

    @classmethod
    def rejected(cls, input_id: str, reason: str) -> SteeringReceipt:
        return cls(input_id=input_id, status=REJECTED, reason=reason)


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedReceipt:
    """What became of one input queued for the next turn, answered immediately.

    ``queued`` and ``rejected`` only: the turn the input becomes is decided after
    the current one ends, and is reported then as
    :class:`~super_agent.frontend.notifications.QueuedInputAccepted`. A front end
    that showed the input as sent would be promising something the application has
    only promised to try.
    """

    input_id: str = ""
    status: str = REJECTED
    reason: str = ""

    @classmethod
    def queued(cls, input_id: str) -> QueuedReceipt:
        return cls(input_id=input_id, status=QUEUED)

    @classmethod
    def rejected(cls, input_id: str, reason: str) -> QueuedReceipt:
        return cls(input_id=input_id, status=REJECTED, reason=reason)


@dataclasses.dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    """What became of one answer to a tool approval, answered immediately.

    ``accepted`` means the decision reached the runtime for the request it named.
    ``rejected`` covers every other outcome — a request that was already answered,
    one that is no longer pending, or one this front end never saw — and the reason
    says which. A front end must show the refusal rather than assume its click
    counted: a decision that arrives after the fact would otherwise look like it
    had a say in a tool call it never saw.
    """

    request_id: str = ""
    status: str = REJECTED
    reason: str = ""

    @classmethod
    def accepted(cls, request_id: str) -> ApprovalReceipt:
        return cls(request_id=request_id, status=ACCEPTED)

    @classmethod
    def rejected(cls, request_id: str, reason: str) -> ApprovalReceipt:
        return cls(request_id=request_id, status=REJECTED, reason=reason)


@dataclasses.dataclass(frozen=True, slots=True)
class ConversationView:
    """One read of conversation state, for a full transcript rebuild."""

    agent_status: AgentStatus = dataclasses.field(default_factory=AgentStatus)
    messages: tuple[Message, ...] = ()
    pending_tool: ToolCall | None = None
    pending_permission: PermissionRequest | None = None
    pending_tool_batch_index: int = 0
    pending_tool_batch_total: int = 0
    #: The request the pending approval belongs to. A front end that rebuilt from
    #: this snapshot answers with this id; empty means nothing is pending.
    pending_approval_id: str = ""
    streaming_message: Message | None = None
