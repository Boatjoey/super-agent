"""Fan-out of conversation events to every connected browser.

One session, many tabs. A subscriber is a bounded queue: a tab that stops reading
drops events instead of growing without limit or stalling the turn, and the next
``snapshot`` event puts it back in step. That is why every event carries the whole
accumulated state it describes rather than a delta a consumer must have missed
nothing to apply.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

__all__ = ["EventHub", "Subscription"]


class Subscription:
    """One reader's view of the stream.

    Usable directly as ``async for``. :meth:`aclose` is what the HTTP handler calls
    when the browser goes away, so a dead tab stops holding a queue.
    """

    __slots__ = ("_hub", "_queue")

    def __init__(self, hub: EventHub, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._hub = hub
        self._queue = queue

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self._queue.get()
            if event.get("kind") == "Closed":
                return
            yield event

    async def get(self) -> dict[str, Any]:
        """The next event, or a ``Closed`` marker once the hub shut down."""
        return await self._queue.get()

    def aclose(self) -> None:
        """Stop receiving. Idempotent."""
        self._hub.unsubscribe(self)


class EventHub:
    """Publish one event to every subscription, dropping for slow readers."""

    __slots__ = ("_maxsize", "_subscriptions")

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._subscriptions: dict[Subscription, asyncio.Queue[dict[str, Any]]] = {}

    @property
    def subscribers(self) -> int:
        """How many readers are attached, for a health check and for tests."""
        return len(self._subscriptions)

    def subscribe(self, *, greeting: dict[str, Any] | None = None) -> Subscription:
        """Attach a reader, optionally with the state it needs before any event."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        subscription = Subscription(self, queue)
        self._subscriptions[subscription] = queue
        if greeting is not None:
            queue.put_nowait(greeting)
        return subscription

    def publish(self, event: dict[str, Any]) -> None:
        """Send one event. A full queue drops it rather than blocking the turn.

        The drop is visible: a later ``snapshot`` event carries the whole view, so
        a tab that missed something converges instead of showing a partial turn
        forever.
        """
        for queue in tuple(self._subscriptions.values()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    def unsubscribe(self, subscription: Subscription) -> None:
        """Detach one reader. Unsubscribing twice is harmless."""
        self._subscriptions.pop(subscription, None)

    def close(self) -> None:
        """Tell every reader that nothing more will arrive."""
        for queue in tuple(self._subscriptions.values()):
            try:
                queue.put_nowait({"kind": "Closed"})
            except asyncio.QueueFull:
                continue
        self._subscriptions.clear()
