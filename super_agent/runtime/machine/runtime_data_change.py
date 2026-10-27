"""The twenty-three runtime-data changes a transition can request.

Each is a frozen value. A change describes what to do; the applier is what does
it, on a clone, in order, followed by a fresh validation.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar, Final

from super_agent.runtime.machine.queued import QueuedInput
from super_agent.runtime.machine.steering import SteeringInput
from super_agent.runtime.permission.types import Request as PermissionRequest
from super_agent.runtime.protocol.types import Attachment, Message, StreamChunk, ToolCall


class RuntimeDataChange:
    """Base class for the sealed runtime-data-change set."""

    __slots__ = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            raise TypeError(
                f"{cls.__name__} extends the sealed RuntimeDataChange set, which may only be declared in {__name__}"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class AppendUserMessage(RuntimeDataChange):
    kind: ClassVar[str] = "AppendUserMessage"

    content: str = ""
    attachments: tuple[Attachment, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class AppendAssistantMessage(RuntimeDataChange):
    kind: ClassVar[str] = "AppendAssistantMessage"

    message: Message = dataclasses.field(default_factory=Message)


@dataclasses.dataclass(frozen=True, slots=True)
class AppendToolResult(RuntimeDataChange):
    kind: ClassVar[str] = "AppendToolResult"

    call: ToolCall = dataclasses.field(default_factory=ToolCall)
    result: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class AppendStreamingAssistant(RuntimeDataChange):
    kind: ClassVar[str] = "AppendStreamingAssistant"

    chunk: StreamChunk = dataclasses.field(default_factory=StreamChunk)


@dataclasses.dataclass(frozen=True, slots=True)
class FlushStreamingAssistant(RuntimeDataChange):
    kind: ClassVar[str] = "FlushStreamingAssistant"

    interrupted: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class SetPendingTool(RuntimeDataChange):
    kind: ClassVar[str] = "SetPendingTool"

    call: ToolCall = dataclasses.field(default_factory=ToolCall)
    request: PermissionRequest = dataclasses.field(default_factory=PermissionRequest)


@dataclasses.dataclass(frozen=True, slots=True)
class SetToolCallBatch(RuntimeDataChange):
    kind: ClassVar[str] = "SetToolCallBatch"

    id: str = ""
    calls: tuple[ToolCall, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class AdvanceToolCallBatch(RuntimeDataChange):
    kind: ClassVar[str] = "AdvanceToolCallBatch"


@dataclasses.dataclass(frozen=True, slots=True)
class ClearPendingTool(RuntimeDataChange):
    kind: ClassVar[str] = "ClearPendingTool"


@dataclasses.dataclass(frozen=True, slots=True)
class SetCurrentTool(RuntimeDataChange):
    kind: ClassVar[str] = "SetCurrentTool"

    call: ToolCall = dataclasses.field(default_factory=ToolCall)


@dataclasses.dataclass(frozen=True, slots=True)
class ClearCurrentTool(RuntimeDataChange):
    kind: ClassVar[str] = "ClearCurrentTool"


@dataclasses.dataclass(frozen=True, slots=True)
class ClearToolCallBatch(RuntimeDataChange):
    kind: ClassVar[str] = "ClearToolCallBatch"


@dataclasses.dataclass(frozen=True, slots=True)
class OpenTurn(RuntimeDataChange):
    """Number the turn being started. Paired with :class:`OpenStep`."""

    kind: ClassVar[str] = "OpenTurn"


@dataclasses.dataclass(frozen=True, slots=True)
class OpenStep(RuntimeDataChange):
    """Start the first step of a turn. Refused while a step is open."""

    kind: ClassVar[str] = "OpenStep"


@dataclasses.dataclass(frozen=True, slots=True)
class AdvanceStep(RuntimeDataChange):
    """End the current step and open the next one. Refused without an open step."""

    kind: ClassVar[str] = "AdvanceStep"


@dataclasses.dataclass(frozen=True, slots=True)
class CloseStep(RuntimeDataChange):
    """End the current step. Tolerates having no step to close."""

    kind: ClassVar[str] = "CloseStep"


@dataclasses.dataclass(frozen=True, slots=True)
class QueueSteering(RuntimeDataChange):
    """Hold an in-turn input until the next step begins."""

    kind: ClassVar[str] = "QueueSteering"

    input: SteeringInput = dataclasses.field(default_factory=SteeringInput)


@dataclasses.dataclass(frozen=True, slots=True)
class AcceptSteering(RuntimeDataChange):
    """Append every held input to the conversation, in submission order.

    Tolerates an empty queue, like :class:`CloseStep`: a transition that reaches a
    step boundary requests the acceptance whether or not anything is waiting.
    """

    kind: ClassVar[str] = "AcceptSteering"


@dataclasses.dataclass(frozen=True, slots=True)
class ClearSteering(RuntimeDataChange):
    """Discard every held input, for a turn that is ending."""

    kind: ClassVar[str] = "ClearSteering"


@dataclasses.dataclass(frozen=True, slots=True)
class QueueInput(RuntimeDataChange):
    """Hold an input until the next turn starts."""

    kind: ClassVar[str] = "QueueInput"

    input: QueuedInput = dataclasses.field(default_factory=QueuedInput)


@dataclasses.dataclass(frozen=True, slots=True)
class TakeQueued(RuntimeDataChange):
    """Remove the queued input this turn was started from.

    Tolerates naming nothing: an empty or unknown id leaves the queue untouched.
    The input may have been discarded a moment earlier, and the turn it now starts
    stands on its own text either way.
    """

    kind: ClassVar[str] = "TakeQueued"

    input_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class ClearQueued(RuntimeDataChange):
    """Discard every queued input, for a cancellation the user asked for."""

    kind: ClassVar[str] = "ClearQueued"


@dataclasses.dataclass(frozen=True, slots=True)
class ResetConversation(RuntimeDataChange):
    kind: ClassVar[str] = "ResetConversation"


#: Every change type as a zero value, in declaration order.
ALL_RUNTIME_DATA_CHANGES: Final[tuple[RuntimeDataChange, ...]] = (
    AppendUserMessage(),
    AppendAssistantMessage(),
    AppendToolResult(),
    AppendStreamingAssistant(),
    FlushStreamingAssistant(),
    SetPendingTool(),
    SetToolCallBatch(),
    AdvanceToolCallBatch(),
    ClearPendingTool(),
    SetCurrentTool(),
    ClearCurrentTool(),
    ClearToolCallBatch(),
    OpenTurn(),
    OpenStep(),
    AdvanceStep(),
    CloseStep(),
    QueueSteering(),
    AcceptSteering(),
    ClearSteering(),
    QueueInput(),
    TakeQueued(),
    ClearQueued(),
    ResetConversation(),
)
