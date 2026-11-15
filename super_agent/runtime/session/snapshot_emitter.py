"""Turn engine snapshots into the notification stream.

Three jobs, all about not repeating yourself: message appends are emitted once
each no matter how often the snapshot is taken, an approval is announced once per
pending tool even though every snapshot while that tool waits looks identical,
and an input is reported once when it leaves its queue.

The emitter is the reason a repeated identical tool call in a batch still prompts
twice: consuming a decision clears ``last_approval_call``, so the next snapshot with
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

import asyncio
import contextlib
from collections import deque

from super_agent.runtime.engine import EngineView
from super_agent.runtime.machine import STATE_IDLE
from super_agent.runtime.permission.types import Request as PermissionRequest
from super_agent.runtime.protocol.types import ToolCall
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


class SnapshotEmitter:
    """Deduplicates the notification stream across repeated snapshots."""

    __slots__ = (
        "_delivery_failure",
        "_delivery_task",
        "_pending",
        "emitted_messages",
        "has_approval",
        "last_approval_call",
        "queued_ids",
        "steering_ids",
    )

    def __init__(self) -> None:
        self._pending: deque[SessionNotification] = deque()
        self._delivery_task: asyncio.Task[None] | None = None
        self._delivery_failure: Exception | None = None
        self.emitted_messages = 0
        self.has_approval = False
        self.last_approval_call: ToolCall | None = None
        self.steering_ids: tuple[str, ...] = ()
        self.queued_ids: tuple[str, ...] = ()

    def mark_approval_consumed(self) -> None:
        """Called once a decision is made, before the engine applies it.

        ``has_approval`` stays set, so a following snapshot without a pending tool
        still emits :class:`ToolApprovalCleared`.
        """
        self.last_approval_call = None

    def reset(self, emitted_messages: int) -> None:
        """Re-arm after a context reset, keeping the messages the engine still holds."""
        if self._delivery_task is not None:
            self._delivery_task.cancel()
            self._delivery_task = None
        self._pending.clear()
        self._delivery_failure = None
        self.emitted_messages = emitted_messages
        self.has_approval = False
        self.last_approval_call = None
        self.steering_ids = ()
        self.queued_ids = ()

    async def emit(self, notifications: asyncio.Queue[SessionNotification], snapshot: EngineView) -> None:
        """Stage a committed snapshot without waiting for the frontend consumer."""
        self._capture(self._pending, snapshot)
        self._publish(notifications)

    def _capture(self, notifications: deque[SessionNotification], snapshot: EngineView) -> None:
        """Capture state, approval, messages, then input receipts atomically."""
        notifications.append(StateChanged(state=snapshot.state))

        pending = snapshot.pending_tool
        if pending is not None:
            if not self.has_approval or self.last_approval_call is None or self.last_approval_call != pending:
                notifications.append(
                    ToolApprovalRequested(
                        tool_call=pending,
                        request=permission_request(snapshot),
                        batch_id=snapshot.pending_tool_batch_id,
                        batch_index=snapshot.pending_tool_batch_index,
                        batch_total=snapshot.pending_tool_batch_total,
                    )
                )
                self.last_approval_call = pending
                self.has_approval = True
        else:
            if self.has_approval:
                notifications.append(ToolApprovalCleared())
            self.has_approval = False
            self.last_approval_call = None

        messages = snapshot.messages
        if self.emitted_messages > len(messages):
            self.emitted_messages = 0
        for message in messages[self.emitted_messages :]:
            notifications.append(MessageAppended(message=message))
        self.emitted_messages = len(messages)

        # Last, so a consumer that renders as it reads already has the message an
        # accepted input became before it is told the input landed.
        self._emit_steering(notifications, snapshot)
        self._emit_queued(notifications, snapshot)

    def _check_delivery(self) -> None:
        if self._delivery_task is not None and self._delivery_task.done():
            self._delivery_task = None
        if self._delivery_failure is not None:
            failure = self._delivery_failure
            self._delivery_failure = None
            raise failure

    def _publish(self, notifications: asyncio.Queue[SessionNotification]) -> None:
        self._check_delivery()
        if self._delivery_task is not None:
            return
        while self._pending:
            try:
                notifications.put_nowait(self._pending[0])
            except asyncio.QueueFull:
                self._delivery_task = asyncio.create_task(self._deliver(notifications))
                return
            self._pending.popleft()

    async def _deliver(self, notifications: asyncio.Queue[SessionNotification]) -> None:
        try:
            while self._pending:
                await notifications.put(self._pending[0])
                self._pending.popleft()
        except Exception as failure:
            self._delivery_failure = failure

    async def flush(self, notifications: asyncio.Queue[SessionNotification]) -> None:
        """Finish delivery at the turn boundary, after committed messages are saved."""
        self._publish(notifications)
        if self._delivery_task is not None:
            await self._delivery_task
        self._check_delivery()

    async def stop_delivery(self) -> None:
        """Retire a delivery task while retaining anything it has not sent."""
        task = self._delivery_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self._delivery_task = None

    def _emit_steering(self, notifications: deque[SessionNotification], snapshot: EngineView) -> None:
        """Report each held input that left the queue since the last snapshot."""
        current = tuple(item.id for item in snapshot.steering if item.id)
        gone = tuple(input_id for input_id in self.steering_ids if input_id not in current)
        self.steering_ids = current
        if snapshot.state == STATE_IDLE:
            for input_id in gone:
                notifications.append(SteeringWithdrawn(input_id=input_id))
            return
        for input_id in gone:
            notifications.append(SteeringAccepted(input_id=input_id, step=snapshot.step_index))

    def _emit_queued(self, notifications: deque[SessionNotification], snapshot: EngineView) -> None:
        """Report each queued input that left the queue since the last snapshot."""
        current = tuple(item.id for item in snapshot.queued if item.id)
        gone = tuple(input_id for input_id in self.queued_ids if input_id not in current)
        self.queued_ids = current
        if snapshot.state == STATE_IDLE:
            for input_id in gone:
                notifications.append(QueuedInputWithdrawn(input_id=input_id))
            return
        for input_id in gone:
            notifications.append(QueuedInputAccepted(input_id=input_id, turn=snapshot.turn_index))


def permission_request(snapshot: EngineView) -> PermissionRequest:
    permission = snapshot.pending_permission
    return permission if permission is not None else PermissionRequest()
