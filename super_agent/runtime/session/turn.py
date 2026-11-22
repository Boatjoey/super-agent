"""Running one turn: notifications out, approvals in.

The session never schedules anything. Approval arrives through
:class:`~super_agent.runtime.execution.ApprovalWaiter`, which the engine calls from
inside a scheduled action, which is why there is no second loop here.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from super_agent.errors import CancellationError, JoinedError
from super_agent.runtime.engine import Engine, EngineView
from super_agent.runtime.execution import ERR_APPROVAL_DISMISSED, ApprovalWaiter
from super_agent.runtime.machine import ApprovalDecision, UserMessageSubmitted
from super_agent.runtime.permission.types import Request as PermissionRequest
from super_agent.runtime.protocol import telemetry
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import Attachment, StreamChunk, ToolCall, Usage
from super_agent.runtime.session.notifications import (
    NOTIFICATIONS_CLOSED,
    SessionError,
    SessionNotification,
    StreamChunkReceived,
    UsageReported,
)
from super_agent.runtime.session.persistence import ErrorPersistenceError

if TYPE_CHECKING:
    from super_agent.runtime.session.repository import Repository, SessionID
    from super_agent.runtime.session.snapshot_emitter import SnapshotEmitter


class ApprovalsClosed:
    """Pushed onto the approvals queue when the interface stops offering decisions.

    An :class:`asyncio.Queue` cannot be closed, so the close is delivered as a
    value; :func:`wait_approval` turns it into
    :data:`~super_agent.runtime.execution.ERR_APPROVAL_DISMISSED`.
    """


#: The close marker for the approvals queue.
APPROVALS_CLOSED = ApprovalsClosed()


async def wait_approval(
    ctx: RunContext, approvals: asyncio.Queue[ApprovalDecision | ApprovalsClosed]
) -> ApprovalDecision:
    """Wait for a decision or for the run to be cancelled, whichever is first.

    A closed queue means the interface went away, which the engine treats as a
    cancellation rather than a fault — the difference matters because a fault is
    reported to the model as a tool error and a cancellation is not.
    """
    getter = asyncio.ensure_future(approvals.get())
    cancelled = asyncio.ensure_future(ctx.done().wait())
    try:
        done, _pending = await asyncio.wait({getter, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            decision = getter.result()
            if isinstance(decision, ApprovalsClosed):
                error = ctx.err()
                if error is not None:
                    raise error
                raise ERR_APPROVAL_DISMISSED
            return decision
        raise CancellationError("run cancelled")
    finally:
        for waiter in (getter, cancelled):
            if not waiter.done():
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter


class TurnMixin:
    """``run_turn`` and its failure path."""

    if TYPE_CHECKING:
        engine: Engine
        emitter: SnapshotEmitter
        repository: Repository | None
        _attachments: list[Attachment]

        def _try_lock(self) -> bool: ...
        def _unlock(self) -> None: ...
        def meta_id(self) -> SessionID: ...
        def snapshot(self) -> EngineView: ...
        async def emit_snapshot(self, notifications: asyncio.Queue[SessionNotification]) -> None: ...
        def persist_turn_boundary(self) -> None: ...
        def persist_approval(self, decision: ApprovalDecision, call: ToolCall) -> None: ...
        def persist_error(self, error: BaseException | None) -> None: ...

    async def run_turn(
        self,
        ctx: RunContext,
        query: str,
        notifications: asyncio.Queue[SessionNotification],
        approvals: asyncio.Queue[ApprovalDecision | ApprovalsClosed],
        input_id: str = "",
    ) -> None:
        """Run one turn, publishing notifications and consuming approval decisions.

        ``input_id`` names the queued input this turn was started from, if any.
        Starting the turn is that input's acceptance point, so the machine needs the
        id in the same transition that appends the message: a caller that submits
        the text without it still gets its turn, just with no acceptance to report.
        """
        try:
            if not self._try_lock():
                raise RuntimeError("session is already running a turn")
            try:
                self.persist_turn_boundary()

                async def observer() -> None:
                    await self.emit_snapshot(notifications)  # type: ignore[attr-defined]

                def on_usage(usage: Usage | None) -> None:
                    # The provider's counts for one model call, forwarded as they
                    # arrive. A response the adapter could not measure carries no
                    # counts, so there is nothing to report. A full queue drops this
                    # rather than blocking the model, the way a stream chunk is
                    # dropped.
                    if usage is None:
                        return
                    with contextlib.suppress(asyncio.QueueFull):
                        notifications.put_nowait(UsageReported(usage=usage))

                # Track live state transitions while actions drain: states such as
                # RunningTool and AdvancingQueue pass between snapshot points, and
                # the header should follow them as they happen.
                self.engine.set_state_observer(observer)
                self.engine.set_model_usage_observer(on_usage)
                try:
                    error = await self._run(ctx, query, notifications, approvals, input_id)
                finally:
                    self.engine.set_model_usage_observer(None)
                    self.engine.set_state_observer(None)
                    await self.emitter.stop_delivery()
            finally:
                self._unlock()
        finally:
            # The end-of-turn close, registered first and therefore run last: the
            # observer is already cleared and the turn lock released by the time
            # the consumer sees this.
            #
            # A bounded queue can be full here, and raising `QueueFull` from a
            # `finally` would replace whatever the turn actually produced — the
            # error the caller must see would be masked by a delivery detail. The
            # delivery is therefore best effort; the authoritative end-of-turn
            # signal is this call returning, which callers and the notification
            # bridge both observe.
            with contextlib.suppress(asyncio.QueueFull):
                notifications.put_nowait(NOTIFICATIONS_CLOSED)

        if error is not None:
            raise error

    async def _run(
        self,
        ctx: RunContext,
        query: str,
        notifications: asyncio.Queue[SessionNotification],
        approvals: asyncio.Queue[ApprovalDecision | ApprovalsClosed],
        input_id: str = "",
    ) -> BaseException | None:
        def on_stream_chunk(chunk: StreamChunk) -> None:
            # A full queue drops this chunk rather than blocking the model. The
            # notification carries the whole accumulated message, so the consumer
            # converges on the same text from the next one.
            notification = StreamChunkReceived(chunk=chunk, message=self.snapshot().streaming_message)
            with contextlib.suppress(asyncio.QueueFull):
                notifications.put_nowait(notification)

        waiter = self._approval_waiter(approvals)

        attachments = list(self._attachments)
        self._attachments = []

        try:
            await self.engine.run_turn(
                ctx,
                UserMessageSubmitted(content=query, attachments=tuple(attachments), input_id=input_id),
                on_stream_chunk,
                waiter,
            )
        except Exception as failure:
            error = self.fail_turn(notifications, failure)
        else:
            error = None
        try:
            await self.emit_snapshot(notifications)
        except Exception as failure:
            error = failure if error is None else JoinedError(error, failure)
        try:
            await self.emitter.flush(notifications)
        except Exception as failure:
            error = failure if error is None else JoinedError(error, failure)
        return error

    def _approval_waiter(self, approvals: asyncio.Queue[ApprovalDecision | ApprovalsClosed]) -> ApprovalWaiter:
        """Bridge the queue to the engine's approval port.

        The decision is persisted and the emitter re-armed *before* the engine
        applies it, so an audit record exists even if the run is cancelled in the
        next instant, and the next identical call prompts again.
        """

        async def wait(ctx: RunContext, call: ToolCall, _request: PermissionRequest) -> ApprovalDecision:
            decision = await wait_approval(ctx, approvals)
            self.persist_approval(decision, call)
            self.emitter.mark_approval_consumed()
            return decision

        return _WaitApprovalFunc(wait)

    def fail_turn(self, notifications: asyncio.Queue[SessionNotification], failure: BaseException) -> BaseException:
        """Keep the execution error primary while attempting both reporting paths."""
        failures: list[BaseException] = [failure]
        try:
            self.persist_error(failure)
        except Exception as persistence_error:
            failures.append(ErrorPersistenceError(persistence_error))
            _record_reporting_failure("error_persistence_failed", persistence_error)
        try:
            notifications.put_nowait(SessionError(err=failure))
        except asyncio.QueueFull as notification_error:
            _record_reporting_failure("error_notification_dropped", notification_error)
        except Exception as notification_error:
            failures.append(notification_error)
            _record_reporting_failure("error_notification_dropped", notification_error)
        if len(failures) == 1:
            return failure
        reported = JoinedError(*failures)
        reported.__cause__ = failure
        return reported


def _record_reporting_failure(kind: str, failure: Exception) -> None:
    # Telemetry is itself a reporting path and must not replace the execution error.
    with contextlib.suppress(Exception):
        telemetry.record(kind, {"error": str(failure), "error_type": type(failure).__name__})


class _WaitApprovalFunc:
    """Adapts a plain async function to the ``ApprovalWaiter`` protocol."""

    __slots__ = ("_wait",)

    def __init__(self, wait: Callable[[RunContext, ToolCall, PermissionRequest], Awaitable[ApprovalDecision]]) -> None:
        self._wait = wait

    async def wait_approval(self, ctx: RunContext, call: ToolCall, request: PermissionRequest) -> ApprovalDecision:
        return await self._wait(ctx, call, request)
