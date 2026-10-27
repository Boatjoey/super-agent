"""What a front end is told while a turn runs.

The set is closed: a subclass declared anywhere but this module is refused, so a
transport cannot be handed a kind the mapping table does not know. Every front end
maps these kinds onto its own vocabulary — a terminal repaint, a server-sent
event, an editor's ``session/update`` — and an unknown runtime notification
becomes :class:`ConversationError` rather than being dropped.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar, Final

from super_agent.frontend.failure import Failure
from super_agent.frontend.view import (
    AgentStatus,
    ContextUsage,
    Message,
    PermissionRequest,
    ToolCall,
)

__all__ = [
    "NOTIFICATION_KINDS",
    "AgentStatusChanged",
    "ConversationError",
    "ConversationNotification",
    "MessageAppended",
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
    "SteeringAccepted",
    "SteeringWithdrawn",
    "StreamChunkReceived",
    "ToolApprovalCleared",
    "ToolApprovalRequested",
    "UsageReported",
]


class ConversationNotification:
    """Base class for the sealed conversation-notification set."""

    __slots__ = ()

    #: The literal notification name, one per kind.
    kind: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(
                f"{cls.__name__} extends the sealed ConversationNotification set, which may only be "
                f"declared in {__name__}"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class AgentStatusChanged(ConversationNotification):
    """The agent moved between presentation states."""

    kind: ClassVar[str] = "AgentStatusChanged"

    status: AgentStatus = dataclasses.field(default_factory=AgentStatus)


@dataclasses.dataclass(frozen=True, slots=True)
class ToolApprovalRequested(ConversationNotification):
    """The runtime is holding a tool call until the user decides.

    ``request_id`` names this request. Answering with
    :meth:`~super_agent.frontend.ports.TurnPort.approve` quotes it back, so a
    decision cannot be applied to a request the user never saw — a second click, a
    reconnected tab, or a request that has already been answered.
    """

    kind: ClassVar[str] = "ToolApprovalRequested"

    tool_call: ToolCall = dataclasses.field(default_factory=ToolCall)
    request: PermissionRequest = dataclasses.field(default_factory=PermissionRequest)
    request_id: str = ""
    batch_index: int = 0
    batch_total: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class ToolApprovalCleared(ConversationNotification):
    """The pending request is gone; nothing is waiting on the user.

    ``request_id`` names the request that ended, so a front end that was showing a
    stale prompt knows which one to stop showing.
    """

    kind: ClassVar[str] = "ToolApprovalCleared"

    request_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class StreamChunkReceived(ConversationNotification):
    """The message being streamed changed."""

    kind: ClassVar[str] = "StreamChunkReceived"

    message: Message | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class MessageAppended(ConversationNotification):
    """One message joined the transcript."""

    kind: ClassVar[str] = "MessageAppended"

    message: Message = dataclasses.field(default_factory=Message)


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringAccepted(ConversationNotification):
    """A held in-turn input joined the conversation at ``step``."""

    kind: ClassVar[str] = "SteeringAccepted"

    input_id: str = ""
    step: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringWithdrawn(ConversationNotification):
    """A held in-turn input was dropped: the turn ended before it was taken up."""

    kind: ClassVar[str] = "SteeringWithdrawn"

    input_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedInputAccepted(ConversationNotification):
    """A queued input started the turn it was waiting for.

    ``turn`` names that turn, because a queued input outlives the stream it was
    submitted on: the acceptance can arrive on a channel the submitter never held.
    """

    kind: ClassVar[str] = "QueuedInputAccepted"

    input_id: str = ""
    turn: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedInputWithdrawn(ConversationNotification):
    """A queued input was dropped: the turn it waited behind was cancelled."""

    kind: ClassVar[str] = "QueuedInputWithdrawn"

    input_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class UsageReported(ConversationNotification):
    """The provider reported what the latest model call cost in tokens."""

    kind: ClassVar[str] = "UsageReported"

    usage: ContextUsage = dataclasses.field(default_factory=ContextUsage)


@dataclasses.dataclass(frozen=True, slots=True)
class ConversationError(ConversationNotification):
    """The turn failed.

    The payload is a display value rather than an exception: a front end shows the
    message and reads ``code`` to know whether its input was ever accepted, which
    is a question an exception's type cannot answer.
    """

    kind: ClassVar[str] = "ConversationError"

    failure: Failure = dataclasses.field(default_factory=Failure)


NOTIFICATION_KINDS: Final[tuple[str, ...]] = (
    "AgentStatusChanged",
    "ToolApprovalRequested",
    "ToolApprovalCleared",
    "StreamChunkReceived",
    "MessageAppended",
    "UsageReported",
    "ConversationError",
    "SteeringAccepted",
    "SteeringWithdrawn",
    "QueuedInputAccepted",
    "QueuedInputWithdrawn",
)
"""The eleven notification kinds, so a test can pin the sealed set."""
