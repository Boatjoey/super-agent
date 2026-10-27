"""The two Python primitives a front-end port is built from.

Both exist because of how Python's concurrency model differs from the runtime's
assumptions, not because a front end has a say in how a turn is scheduled.
"""

from __future__ import annotations

import asyncio
from collections import deque


class Channel[T]:
    """A queue: buffered puts, one consumer, and an explicit close.

    The producer closes it to say "no more will arrive"; a listener then ends.
    ``asyncio.Queue`` has no close, so the close is a flag and :meth:`get` returns
    ``None`` on it.
    """

    __slots__ = ("_closed", "_items", "_ready")

    def __init__(self) -> None:
        self._items: deque[T] = deque()
        self._closed = False
        self._ready = asyncio.Event()

    def put(self, value: T) -> None:
        """Send one value. A send after the close is dropped, not delivered."""
        if self._closed:
            return
        self._items.append(value)
        self._ready.set()

    def close(self) -> None:
        """Say that no more values will arrive."""
        self._closed = True
        self._ready.set()

    @property
    def closed(self) -> bool:
        """Whether the producer has closed the channel."""
        return self._closed

    async def get(self) -> T | None:
        """The next value, or ``None`` once the channel is closed and drained."""
        while True:
            if self._items:
                return self._items.popleft()
            if self._closed:
                return None
            # Nothing to read and nothing closed: wait. No await sits between the
            # test above and the clear below, so a put cannot be missed.
            self._ready.clear()
            await self._ready.wait()


class Cancellation:
    """The cancellation of one turn, as a value rather than a task handle.

    A value because the turn's command may not have started when the user
    cancels: the cancel is already visible by then, and a cancelled
    ``asyncio.Task`` would simply never run.
    """

    __slots__ = ("_cancelled", "_event")

    def __init__(self) -> None:
        self._cancelled = False
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        """Whether the turn has been cancelled."""
        return self._cancelled

    def cancel(self) -> None:
        """Cancel the turn. Idempotent."""
        self._cancelled = True
        self._event.set()

    async def wait(self) -> None:
        """Block until the turn is cancelled, for ports that can race it."""
        await self._event.wait()
