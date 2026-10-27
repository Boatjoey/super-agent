"""The read-only view of the engine that callers and observers consume."""

from __future__ import annotations

import dataclasses

from super_agent.runtime.machine import (
    STATE_INITIALIZING,
    Message,
    PermissionRequest,
    QueuedInput,
    State,
    SteeringInput,
    ToolCall,
)


@dataclasses.dataclass(frozen=True, slots=True)
class EngineView:
    """A consistent snapshot of engine state.

    ``is_busy`` and ``needs_input`` are derived here rather than by each caller, so
    every presentation layer agrees about what "working" and "waiting for you"
    mean.

    ``step_index``, ``steering``, and ``queued`` are what a submission needs to be
    reported against: the step an input would join, the inputs already waiting for
    it, and the inputs waiting for the next turn. ``turn_index`` numbers the turn
    those reports are about.
    """

    state: State = STATE_INITIALIZING
    messages: tuple[Message, ...] = ()
    pending_tool: ToolCall | None = None
    pending_permission: PermissionRequest | None = None
    pending_tool_batch_id: str = ""
    pending_tool_batch_index: int = 0
    pending_tool_batch_total: int = 0
    streaming_message: Message | None = None
    is_busy: bool = False
    needs_input: bool = False
    #: The current step of the running turn; ``0`` when no step is open.
    step_index: int = 0
    #: The current turn of this conversation; ``0`` before the first one starts.
    turn_index: int = 0
    #: In-turn inputs held until the next step begins, in submission order.
    steering: tuple[SteeringInput, ...] = ()
    #: Inputs held until the next turn starts, in submission order.
    queued: tuple[QueuedInput, ...] = ()
