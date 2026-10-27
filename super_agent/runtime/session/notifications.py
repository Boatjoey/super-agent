"""What the session tells the outside world while a turn runs.

Eleven notification kinds carry information. :class:`NotificationsClosed` is the
twelfth member and carries none: an :class:`asyncio.Queue` has no close, so the
end of a turn is delivered as a value the consumer stops on.

Two of them report what happened to a mid-turn input, because holding an input
until the next step is invisible otherwise: :class:`SteeringAccepted` says the
input joined the conversation at a step, and :class:`SteeringWithdrawn` says it
never did. Another two do the same for the queue that belongs to the next turn:
:class:`QueuedInputAccepted` says the input started a turn, and
:class:`QueuedInputWithdrawn` says it was dropped with the turn it waited behind.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar, Final

from super_agent.runtime.machine import (
    Message,
    PermissionRequest,
    State,
    StreamChunk,
    ToolCall,
)
from super_agent.runtime.protocol.types import Usage


class SessionNotification:
    """Base class for the sealed session-notification set."""

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(
                f"{cls.__name__} extends the sealed SessionNotification set, which may only be declared in {__name__}"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class StateChanged(SessionNotification):
    kind: ClassVar[str] = "StateChanged"

    state: State


@dataclasses.dataclass(frozen=True, slots=True)
class ToolApprovalRequested(SessionNotification):
    kind: ClassVar[str] = "ToolApprovalRequested"

    tool_call: ToolCall = dataclasses.field(default_factory=ToolCall)
    request: PermissionRequest = dataclasses.field(default_factory=PermissionRequest)
    batch_id: str = ""
    batch_index: int = 0
    batch_total: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class ToolApprovalCleared(SessionNotification):
    kind: ClassVar[str] = "ToolApprovalCleared"


@dataclasses.dataclass(frozen=True, slots=True)
class StreamChunkReceived(SessionNotification):
    kind: ClassVar[str] = "StreamChunkReceived"

    chunk: StreamChunk = dataclasses.field(default_factory=StreamChunk)
    #: The whole accumulated streaming message, not just this delta, so a consumer
    #: that drops an intermediate chunk still converges on the same text.
    message: Message | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class MessageAppended(SessionNotification):
    kind: ClassVar[str] = "MessageAppended"

    message: Message = dataclasses.field(default_factory=Message)


@dataclasses.dataclass(frozen=True, slots=True)
class UsageReported(SessionNotification):
    """The provider reported what the latest model call cost in tokens.

    Only the provider's own counts travel here: the runtime carries no
    context-window size, so a fraction of the context cannot be derived.
    """

    kind: ClassVar[str] = "UsageReported"

    usage: Usage = dataclasses.field(default_factory=Usage)


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringAccepted(SessionNotification):
    """A held in-turn input joined the conversation at a step.

    ``step`` is the step the input became part of, so the caller can say *when*
    it was taken up rather than only that it was.
    """

    kind: ClassVar[str] = "SteeringAccepted"

    input_id: str = ""
    step: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringWithdrawn(SessionNotification):
    """A held in-turn input never reached the conversation.

    The turn ended first — cancelled, failed, or reset — so the input is gone.
    A consumer must stop showing it as waiting.
    """

    kind: ClassVar[str] = "SteeringWithdrawn"

    input_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedInputAccepted(SessionNotification):
    """A queued input became the turn it was waiting for.

    ``turn`` is the turn that took it up. Unlike steering, the turn is named here
    because the queue outlives the turn the input was submitted under: the
    notification can arrive long after the stream the caller submitted on.
    """

    kind: ClassVar[str] = "QueuedInputAccepted"

    input_id: str = ""
    turn: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedInputWithdrawn(SessionNotification):
    """A queued input never became a turn.

    The user cancelled the turn it was queued behind, so the input is gone. A
    consumer must stop showing it as waiting.
    """

    kind: ClassVar[str] = "QueuedInputWithdrawn"

    input_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class SessionError(SessionNotification):
    kind: ClassVar[str] = "SessionError"

    err: BaseException | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class NotificationsClosed(SessionNotification):
    """The turn has finished and nothing more will arrive.

    The end-of-turn marker. Delivered as a value because
    :class:`asyncio.Queue` cannot be closed, and kept inside the sealed set so the
    queue has one element type.
    """

    kind: ClassVar[str] = "NotificationsClosed"


#: The single value a consumer stops on. One instance, so a test can compare by
#: identity the way a closed channel is a single event.
NOTIFICATIONS_CLOSED: Final[NotificationsClosed] = NotificationsClosed()
