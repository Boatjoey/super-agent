"""One turn at a time, driven by HTTP requests and reported over the hub.

The runtime accepts one turn per session, so this module owns the single slot: it
starts the turn, forwards what the port reports to every browser, and answers the
approval and cancellation requests that arrive while it runs.

Nothing here interprets a notification. The port decides what a turn means; this
module only tags it for the wire.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses

from super_agent import frontend
from super_agent.frontend import (
    Conversation,
    ConversationNotification,
    Decision,
    QueuedReceipt,
    SteeringReceipt,
    wire,
)
from super_agent.web.hub import EventHub

__all__ = ["NoPendingApproval", "TurnBusy", "TurnRunner"]

#: The three answers a browser may send. Anything else is a client bug, and
#: turning it into a decision would execute a tool nobody chose.
DECISIONS: frozenset[str] = frozenset({str(frontend.APPROVE_ONCE), str(frontend.APPROVE_ALWAYS), str(frontend.DENY)})


class TurnBusy(Exception):
    """A turn is already running; the runtime would refuse the second one."""


class NoPendingApproval(Exception):
    """Nothing is waiting for a decision, so a decision would answer nothing."""


@dataclasses.dataclass(slots=True)
class _Pending:
    """The cancel handle a running turn listens on."""

    cancellation: frontend.Cancellation


class TurnRunner:
    """The single turn slot of one session, as a browser sees it."""

    __slots__ = ("_conversation", "_hub", "_pending", "_task")

    def __init__(self, conversation: Conversation, hub: EventHub) -> None:
        self._conversation = conversation
        self._hub = hub
        self._task: asyncio.Task[None] | None = None
        self._pending: _Pending | None = None

    @property
    def running(self) -> bool:
        """Whether a turn is in flight."""
        return self._task is not None and not self._task.done()

    async def start_turn(self, text: str) -> None:
        """Start one turn and return immediately; its events arrive on the hub."""
        if self.running:
            raise TurnBusy("a turn is already running")
        self._task = asyncio.create_task(self._run(text))

    async def steer(self, text: str) -> SteeringReceipt:
        """Submit an in-turn input, answering with what became of it."""
        return await self._conversation.steer(text)

    async def queue(self, text: str) -> QueuedReceipt:
        """Queue an input for the next turn, answering with what became of it.

        Queued input belongs to the turn after this one, so it does not depend on
        a turn running: the port decides, and refuses with a reason when there is
        nothing to queue behind.
        """
        return await self._conversation.queue(text)

    async def approve(self, decision: str, request_id: str) -> None:
        """Answer the approval ``request_id`` names. A stale answer is refused.

        The refusal is the port's, not this module's: only the application knows
        which request is still pending, so only it can say whether this click
        answered one. A turn that is not running has nothing to answer at all.
        """
        if decision not in DECISIONS:
            raise ValueError(f"unknown approval decision: {decision}")
        if self._pending is None:
            raise NoPendingApproval("no tool call is waiting for a decision")
        receipt = await self._conversation.approve(Decision(decision), request_id)
        if receipt.status != frontend.ACCEPTED:
            raise NoPendingApproval(receipt.reason or "the decision answered no pending request")

    async def cancel(self) -> None:
        """Cancel the turn in flight. Idempotent, and honest about doing nothing."""
        pending = self._pending
        if pending is None:
            return
        pending.cancellation.cancel()
        await self._conversation.cancel()

    async def wait(self) -> None:
        """Wait for the running turn, if any. Used by tests and by shutdown."""
        task = self._task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def snapshot_event(self) -> dict[str, object]:
        """The whole view, tagged for the wire.

        Every reconnect and every turn end sends one of these, which is what lets
        a tab that dropped events rebuild rather than guess.
        """
        return {"kind": "Snapshot", "snapshot": wire.view_to_json(self._conversation.snapshot())}

    async def _run(self, text: str) -> None:
        """Run the turn to its end, then tell every tab the new state."""
        notifications: frontend.Channel[ConversationNotification] = frontend.Channel()
        pending = _Pending(cancellation=frontend.Cancellation())
        self._pending = pending
        self._hub.publish({"kind": "TurnStarted"})
        consumer = asyncio.create_task(self._forward(notifications))
        failure: frontend.Failure | None = None
        try:
            failure = await self._conversation.run_turn(text, notifications, pending.cancellation)
        except BaseException as unexpected:
            # The port reports failures by returning them; a raise here is a bug,
            # and it must still end the turn for every connected tab rather than
            # leaving the interface waiting for a completion that will not come.
            failure = frontend.failure_from(unexpected, operation="run_turn")
        finally:
            # The port closes the channel when the turn ends; closing it again is
            # harmless and covers the case where it failed before doing so.
            # Awaiting the consumer is what guarantees every event was published
            # before ``TurnFinished`` tells a tab to stop waiting.
            notifications.close()
            with contextlib.suppress(Exception):
                await consumer
            self._pending = None
        self._hub.publish({"kind": "TurnFinished", "error": wire.failure_to_json(failure)})
        self._hub.publish(self.snapshot_event())

    async def _forward(self, notifications: frontend.Channel[ConversationNotification]) -> None:
        """Publish each notification until the port closes the channel."""
        while (notification := await notifications.get()) is not None:
            self._hub.publish(wire.notification_to_json(notification))
