"""A small HTTP/1.1 server: JSON routes plus one server-sent event stream.

The transport is deliberately smaller than a framework. It speaks exactly what a
browser needs for this interface — ``GET``, ``POST``, ``DELETE``, a JSON body, and
``text/event-stream`` — and nothing else: no chunked requests, no ranges, no
compression, no keep-alive beyond the event stream. That keeps the dependency
list at zero and the behaviour auditable, which is the whole reason a local
harness interface does not need a web framework.

A response closes its connection; the event stream keeps its own open. Both are
stated in the response headers, so a browser does not have to guess.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.parse

from super_agent.web.assets import Assets
from super_agent.web.routes import Request, Response, Router, error_response

__all__ = ["EVENTS_PATH", "Server"]

#: Where the browser subscribes. One stream per tab, for the whole session.
EVENTS_PATH = "/api/events"

#: A request body larger than this is refused. Messages are text; an upload would
#: need a different route rather than a bigger buffer.
MAX_BODY = 1024 * 1024

_REASONS = {
    200: "OK",
    202: "Accepted",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    500: "Internal Server Error",
}


class Server:
    """One listening socket, one router, one asset directory."""

    __slots__ = ("_assets", "_host", "_port", "_router", "_server")

    def __init__(
        self,
        router: Router,
        assets: Assets | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._router = router
        self._assets = assets if assets is not None else Assets()
        self._host = host
        self._server: asyncio.AbstractServer | None = None
        self._port = port

    @property
    def port(self) -> int:
        """The bound port. With ``port=0`` this is the port the kernel chose."""
        return self._port

    async def start(self) -> None:
        """Bind and start accepting. Idempotent enough to be called once."""
        self._server = await asyncio.start_server(self._handle, self._host, self._port, limit=64 * 1024)
        socket = self._server.sockets[0] if self._server.sockets else None
        if socket is not None:
            self._port = int(socket.getsockname()[1])

    async def serve_forever(self) -> None:
        """Serve until :meth:`close`."""
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        """Stop accepting. Connections in flight finish on their own."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Serve one connection, and always give the socket back.

        The close is outside the handler body on purpose: a browser that leaves
        mid-response turns a write into a reset, and a writer left open because of
        it would outlive the failure.
        """
        try:
            await self._serve(reader, writer)
        except (ConnectionError, asyncio.CancelledError):
            # The browser went away: nothing to report and nobody to report it to.
            return
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(_read_request(reader), timeout=30)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            await _write(writer, error_response(400, "malformed request"))
            return
        except PayloadTooLarge:
            await _write(writer, error_response(413, "request body too large"))
            return

        if request.method == "GET" and request.path == EVENTS_PATH:
            await self._stream(reader, writer)
            return
        await _write(writer, await self._route(request))

    async def _route(self, request: Request) -> Response:
        if request.path.startswith("/api/"):
            return await self._router.handle(request)
        if request.method != "GET":
            return error_response(405, "static files are read-only")
        asset = self._assets.read(request.path.lstrip("/"))
        if asset is None:
            return error_response(404, f"no such file: {request.path}")
        body, content_type = asset
        return Response(status=200, body=body, content_type=content_type, headers=(("Cache-Control", "no-store"),))

    async def _stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Hold one connection open and write each event as it is published.

        A closed tab sends nothing, so it is detected by racing the next event
        against a read: end-of-stream on the read is the browser leaving. Without
        that race the handler would wait for an event that will never be written
        for a client that is no longer there, and shutdown would hang on it.
        """
        head = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream; charset=utf-8\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n"
            "X-Accel-Buffering: no\r\n"
            "\r\n"
        )
        writer.write(head.encode("ascii"))
        await writer.drain()
        subscription = self._router.subscribe()
        try:
            while True:
                next_event = asyncio.ensure_future(subscription.get())
                gone = asyncio.ensure_future(reader.read(1))
                done, _pending = await asyncio.wait({next_event, gone}, return_when=asyncio.FIRST_COMPLETED)
                if next_event not in done:
                    next_event.cancel()
                    gone.result()
                    return
                if not gone.done():
                    gone.cancel()
                event = next_event.result()
                kind = str(event.get("kind", "message")).replace("\n", " ")
                payload = json.dumps(event, ensure_ascii=False)
                writer.write(f"event: {kind}\ndata: {payload}\n\n".encode())
                await writer.drain()
                if kind == "Closed":
                    return
        finally:
            subscription.aclose()


class PayloadTooLarge(Exception):
    """The body exceeded :data:`MAX_BODY`."""


async def _read_request(reader: asyncio.StreamReader) -> Request:
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2:
        raise ValueError("malformed request line")
    method, target = parts[0], parts[1]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0") or "0")
    except ValueError as invalid:
        raise ValueError("bad content-length") from invalid
    if length > MAX_BODY:
        raise PayloadTooLarge(length)
    body = await reader.readexactly(length) if length > 0 else b""
    return Request(method=method.upper(), path=urllib.parse.urlsplit(target).path, body=body)


async def _write(writer: asyncio.StreamWriter, response: Response) -> None:
    reason = _REASONS.get(response.status, "OK")
    head = [f"HTTP/1.1 {response.status} {reason}"]
    if response.content_type:
        head.append(f"Content-Type: {response.content_type}")
    head.append(f"Content-Length: {len(response.body)}")
    head.extend(f"{name}: {value}" for name, value in response.headers)
    head.append("Connection: close")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii"))
    writer.write(response.body)
    await writer.drain()
