"""The agent's side of a JSON-RPC connection.

Two directions on one pipe: notifications and requests go out; answers to the
requests come back with the same ``id``. A request waits on a future, so the
permission flow is a plain ``await`` in the middle of a turn rather than a second
state machine.

Nothing here reads or writes bytes. The transport hands whole messages in and
takes whole messages out, which is what makes the protocol testable without a
subprocess.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from super_agent.acp import jsonrpc

__all__ = ["Connection"]

Send = Callable[[dict[str, Any]], Awaitable[None]]


class Connection:
    """Request/response pairing over a write function."""

    __slots__ = ("_next_id", "_pending", "_send")

    def __init__(self, send: Send) -> None:
        self._send = send
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    async def send(self, message: dict[str, Any]) -> None:
        """Write one whole message: a response, an error, or anything else."""
        await self._send(message)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification: no answer is expected."""
        await self._send(jsonrpc.notification(method, params))

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request and wait for its answer.

        A client that answers with an error raises :class:`JsonRpcError`; a client
        that dies is the caller's problem, and the pending future is failed by
        :meth:`close` so no turn waits forever.
        """
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send(jsonrpc.request(request_id, method, params))
            return await future
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, message: dict[str, Any]) -> bool:
        """Deliver a client's answer. Returns whether it matched a request."""
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return False
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        failure = message.get("error")
        if isinstance(failure, dict):
            future.set_exception(
                jsonrpc.JsonRpcError(int(failure.get("code", jsonrpc.INTERNAL_ERROR)), str(failure.get("message", "")))
            )
            return True
        value = message.get("result")
        future.set_result(value if isinstance(value, dict) else {})
        return True

    def close(self) -> None:
        """Fail every pending request, so a dead client does not block a turn."""
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(jsonrpc.JsonRpcError(jsonrpc.INTERNAL_ERROR, "the client disconnected"))
        self._pending.clear()
