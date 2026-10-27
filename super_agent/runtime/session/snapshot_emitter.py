"""Turn engine snapshots into the notification stream.

Three jobs, all about not repeating yourself: message appends are emitted once
each no matter how often the snapshot is taken, an approval is announced once per
pending tool even though every snapshot while that tool waits looks identical,
and an input is reported once when it leaves its queue.

The emitter is the reason a repeated identical tool call in a batch still prompts
twice: consuming a decision clears ``lastApprovalCall``, so the next snapshot with
a pending tool is a new approval even when the call value is equal.

An input leaving a queue is told apart by the queue it left. A held in-turn input
is only emptied two ways: the machine accepts it at a step boundary, or the turn
ends and takes it with it. Acceptance leaves the turn running; the end of a turn
is ``Idle``. An input without an id cannot be named in a receipt, so it is not
announced at all.

The queued-for-next-turn inputs are judged the same way, with one difference in
what the outcome means: leaving the queue while a turn runs is the input *starting*
a turn, and leaving it while idle means the cancellation it waited behind took it
with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from super_agent.runtime.engine import EngineView
from super_agent.runtime.machine import STATE_IDLE, Message, PermissionRequest, ToolCall
from super_agent.runtime.session.notifications import (
    MessageAppended,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    SessionNotification,
    StateChanged,
    SteeringAccepted,
    SteeringWithdrawn,
    ToolApprovalCleared,
    ToolApprovalRequested,
)

if TYPE_CHECKING:
    import asyncio

    from super_agent.runtime.session.notifications import SessionNotification


class SnapshotEmitter:
    """Deduplicates the notification stream across repeated snapshots."""

    __slots__ = ("emittedMessages", "hasApproval", "lastApprovalCall", "queuedIDs", "steeringIDs")

    def __init__(self) -> None:
        self.emittedMessages = 0
        self.hasApproval = False
        self.lastApprovalCall: ToolCall | None = None
        self.steeringIDs: tuple[str, ...] = ()
        self.queuedIDs: tuple[str, ...] = ()

    def markApprovalConsumed(self) -> None:
        """Called once a decision is made, before the engine applies it.

        ``hasApproval`` stays set, so a following snapshot without a pending tool
        still emits :class:`ToolApprovalCleared`.
        """
        self.lastApprovalCall = None

    def reset(self, emittedMessages: int) -> None:
        """Re-arm after a context reset, keeping the messages the engine still holds."""
        self.emittedMessages = emittedMessages
        self.hasApproval = False
        self.lastApprovalCall = None
        self.steeringIDs = ()
        self.queuedIDs = ()

    async def emit(
        self,
        notifications: asyncio.Queue[SessionNotification],
        snapshot: EngineView,
        onMessage: Any = None,
    ) -> None:
        """Publish whatever changed since the last call, in a fixed order.

        State first, then the approval change, then message appends: a consumer
        that renders as it reads must never show an approval against the wrong
        state.
        """
        await notifications.put(StateChanged(state=snapshot.state))

        pending = snapshot.pending_tool
        if pending is not None:
            if not self.hasApproval or self.lastApprovalCall is None or self.lastApprovalCall != pending:
                await notifications.put(
                    ToolApprovalRequested(
                        tool_call=pending,
                        request=permission_request(snapshot),
                        batch_id=snapshot.pending_tool_batch_id,
                        batch_index=snapshot.pending_tool_batch_index,
                        batch_total=snapshot.pending_tool_batch_total,
                    )
                )
                self.lastApprovalCall = pending
                self.hasApproval = True
        else:
            if self.hasApproval:
                await notifications.put(ToolApprovalCleared())
            self.hasApproval = False
            self.lastApprovalCall = None

        messages = snapshot.messages
        if self.emittedMessages > len(messages):
            self.emittedMessages = 0
        for message in messages[self.emittedMessages :]:
            await notifications.put(MessageAppended(message=message))
            if onMessage is not None:
                onMessage(message)
        self.emittedMessages = len(messages)

        # Last, so a consumer that renders as it reads already has the message an
        # accepted input became before it is told the input landed.
        await self._emit_steering(notifications, snapshot)
        await self._emit_queued(notifications, snapshot)

    async def _emit_steering(self, notifications: asyncio.Queue[SessionNotification], snapshot: EngineView) -> None:
        """Report each held input that left the queue since the last snapshot."""
        current = tuple(item.id for item in snapshot.steering if item.id)
        gone = tuple(input_id for input_id in self.steeringIDs if input_id not in current)
        self.steeringIDs = current
        if snapshot.state == STATE_IDLE:
            for input_id in gone:
                await notifications.put(SteeringWithdrawn(input_id=input_id))
            return
        for input_id in gone:
            await notifications.put(SteeringAccepted(input_id=input_id, step=snapshot.step_index))

    async def _emit_queued(self, notifications: asyncio.Queue[SessionNotification], snapshot: EngineView) -> None:
        """Report each queued input that left the queue since the last snapshot."""
        current = tuple(item.id for item in snapshot.queued if item.id)
        gone = tuple(input_id for input_id in self.queuedIDs if input_id not in current)
        self.queuedIDs = current
        if snapshot.state == STATE_IDLE:
            for input_id in gone:
                await notifications.put(QueuedInputWithdrawn(input_id=input_id))
            return
        for input_id in gone:
            await notifications.put(QueuedInputAccepted(input_id=input_id, turn=snapshot.turn_index))


def permission_request(snapshot: EngineView) -> PermissionRequest:
    permission = snapshot.pending_permission
    return permission if permission is not None else PermissionRequest()


_ = Message
