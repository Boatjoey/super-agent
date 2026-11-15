"""The HTTP transport itself: one real socket, one real stream.

The route table and the access rules are tested without a socket; this file
tests only what the socket adds — request framing, the static files, the one
connection that stays open, and that every request meets the access check first.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncGenerator
from typing import cast

import httpx
import pytest

from super_agent import frontend
from super_agent.web import WebAdapter, new_web_adapter, serve
from super_agent.web.server import _read_request  # pyright: ignore[reportPrivateUsage]
from tests.fakes.frontend import FakeFrontendPorts

#: The startup line, exactly as ``serve`` writes it.
ADDRESS_LINE = re.compile(r"super-agent web interface: (http://127\.0\.0\.1:(\d+)/\?token=([A-Za-z0-9_-]{43}))")


@contextlib.asynccontextmanager
async def signed_in(server: WebAdapter) -> AsyncGenerator[httpx.AsyncClient]:
    """A client that got in the way a browser does: by opening the printed address."""
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
        exchange = await client.get(server.address)
        assert exchange.status_code == 303, exchange.text
        yield client


def cookie_header(server: WebAdapter) -> str:
    """The Cookie header the exchange would give a browser, for a hand-written request."""
    token = server.address.rsplit("token=", 1)[1]
    return f"super_agent_{server.port}={token}"


async def raw_head(server: WebAdapter, request: bytes) -> bytes:
    """The status line and headers of one hand-written request."""
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    try:
        writer.write(request)
        await writer.drain()
        return await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def read_event(reader: asyncio.StreamReader) -> tuple[str, dict[str, object]]:
    """One server-sent event, as (event name, decoded payload)."""
    block = await asyncio.wait_for(reader.readuntil(b"\n\n"), timeout=5)
    name = ""
    data = ""
    for line in block.decode("utf-8").split("\n"):
        if line.startswith("event: "):
            name = line[len("event: ") :]
        elif line.startswith("data: "):
            data = line[len("data: ") :]
    return name, json.loads(data)


@pytest.mark.asyncio
async def test_the_page_the_script_and_the_json_surface_are_served() -> None:
    frontend_ports = FakeFrontendPorts(
        agents=[frontend.AgentSummary(name="build", provider="deepseek", model="deepseek-chat", permission_mode="ask")]
    )
    server, _hub, _runner = new_web_adapter(frontend_ports, port=0)
    await server.start()
    try:
        async with signed_in(server) as client:
            page = await client.get("/")
            assert page.status_code == 200
            assert "Super Agent" in page.text
            assert page.headers["content-type"].startswith("text/html")

            script = await client.get("/app.js")
            assert script.status_code == 200
            assert script.headers["content-type"].startswith("text/javascript")

            style = await client.get("/style.css")
            assert style.status_code == 200
            assert style.headers["content-type"].startswith("text/css")

            favicon = await client.get("/favicon.svg")
            assert favicon.status_code == 200
            assert favicon.headers["content-type"].startswith("image/svg+xml")

            missing = await client.get("/missing.js")
            assert missing.status_code == 404

            snapshot = await client.get("/api/snapshot")
            assert snapshot.json()["config"]["model"] == "deepseek-chat"

            health = await client.get("/api/health")
            assert health.json() == {"ok": True, "running": False, "subscribers": 0}
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_the_event_stream_greets_a_tab_then_follows_a_turn() -> None:
    frontend_ports = FakeFrontendPorts(
        notifications=[
            frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="hi")),
        ]
    )
    server, hub, runner = new_web_adapter(frontend_ports, port=0)
    await server.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    try:
        writer.write(
            f"GET /api/events HTTP/1.1\r\nHost: localhost:{server.port}\r\n"
            f"Cookie: {cookie_header(server)}\r\nAccept: text/event-stream\r\n\r\n".encode()
        )
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert b"200 OK" in head
        assert b"text/event-stream" in head

        name, payload = await read_event(reader)
        assert name == "Snapshot"
        snapshot = cast("dict[str, object]", payload["snapshot"])
        agent_status = cast("dict[str, object]", snapshot["agent_status"])
        assert agent_status["label"] == "Idle"

        async with signed_in(server) as client:
            accepted = await client.post("/api/turns", json={"text": "hello"})
        assert accepted.status_code == 202
        await runner.wait()

        names: list[str] = []
        for _ in range(4):
            name, _payload = await read_event(reader)
            names.append(name)
        assert names == ["TurnStarted", "MessageAppended", "TurnFinished", "Snapshot"]
        assert hub.subscribers == 1
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_a_malformed_request_is_answered_rather_than_dropped() -> None:
    server, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    try:
        writer.write(b"nonsense\r\n\r\n")
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert b"400 Bad Request" in head
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_only_the_events_path_streams() -> None:
    """A JSON route never leaves a connection open: the socket closes with it."""
    server, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    try:
        async with signed_in(server) as client:
            response = await client.get("/api/events/extra")
            assert response.status_code == 404
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_the_request_reader_keeps_the_query_string() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET /api/workspace/diagnostics?path=x.py HTTP/1.1\r\nHost: localhost\r\n\r\n")
    reader.feed_eof()

    request = await _read_request(reader)

    assert request.path == "/api/workspace/diagnostics"
    assert request.query == {"path": ["x.py"]}


@pytest.mark.asyncio
async def test_the_request_reader_keeps_the_headers_a_check_needs() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"GET /?token= HTTP/1.1\r\nHost: 127.0.0.1:1\r\nOrigin: http://127.0.0.1:1\r\nCookie: a=b\r\n\r\n")
    reader.feed_eof()

    request = await _read_request(reader)

    assert request.headers == {"host": "127.0.0.1:1", "origin": "http://127.0.0.1:1", "cookie": "a=b"}
    # An empty token is no token: the exchange never sees it.
    assert request.query == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "head",
    [
        b"GET http://attacker.example/ HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n",
        b"GET * HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: 127.0.0.1:1\r\nHost: attacker.example\r\n\r\n",
        b"GET / HTTP/1.1\r\nHost: 127.0.0.1:1\r\nOrigin: http://127.0.0.1:1\r\nOrigin: http://a.example\r\n\r\n",
    ],
)
async def test_a_target_that_is_not_a_path_or_a_repeated_host_or_origin_is_malformed(head: bytes) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(head)
    reader.feed_eof()

    with pytest.raises(ValueError):
        await _read_request(reader)


@pytest.mark.asyncio
async def test_without_the_cookie_neither_the_page_nor_the_api_is_served() -> None:
    frontend_ports = FakeFrontendPorts()
    server, _hub, _runner = new_web_adapter(frontend_ports, port=0)
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
            snapshot = await client.get("/api/snapshot")
            assert snapshot.status_code == 401
            assert snapshot.json() == {"error": "authentication required: open the address printed at startup"}

            turn = await client.post("/api/turns", json={"text": "hello"})
            assert turn.status_code == 401

            for path in ("/", "/app.js", "/style.css"):
                page = await client.get(path)
                assert page.status_code == 401
                assert page.headers["content-type"].startswith("text/html")
                assert "需要访问令牌" in page.text
                assert "<script" not in page.text
        assert frontend_ports.queries == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_the_event_stream_without_the_cookie_is_refused_before_it_opens() -> None:
    server, hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    try:
        head = await raw_head(
            server,
            f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nAccept: text/event-stream\r\n\r\n".encode(),
        )
        assert head.startswith(b"HTTP/1.1 401 Unauthorized\r\n")
        assert b"text/event-stream" not in head
        assert hub.subscribers == 0
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_the_printed_address_exchanges_its_token_for_an_http_only_strict_cookie() -> None:
    server, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        async with httpx.AsyncClient(base_url=base, timeout=5) as client:
            exchange = await client.get(server.address)

            assert exchange.status_code == 303
            assert exchange.headers["location"] == "/"
            assert exchange.headers["cache-control"] == "no-store"
            assert exchange.content == b""
            attributes = [part.strip() for part in exchange.headers["set-cookie"].split(";")]
            assert attributes[0] == cookie_header(server)
            assert sorted(attributes[1:]) == ["HttpOnly", "Path=/", "SameSite=Strict"]

        # A browser follows the redirect: it lands on the bare address, so the
        # token is no longer in the address bar, and the cookie alone opens the page.
        async with httpx.AsyncClient(base_url=base, timeout=5) as browser:
            landed = await browser.get(server.address, follow_redirects=True)
            assert [step.status_code for step in landed.history] == [303]
            assert landed.status_code == 200
            assert str(landed.url) == f"{base}/"
            assert "token" not in str(landed.url)
            assert "Super Agent" in landed.text

            again = await browser.get("/api/snapshot")
            assert again.status_code == 200
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_a_wrong_or_empty_token_sets_no_cookie() -> None:
    server, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
            for target in ("/?token=not-the-token", "/?token="):
                refused = await client.get(target)
                assert refused.status_code == 401
                assert "set-cookie" not in refused.headers
                assert refused.headers["content-type"].startswith("text/html")
            assert len(client.cookies.jar) == 0
            assert (await client.get("/api/health")).status_code == 401
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_a_foreign_origin_is_refused_and_starts_nothing() -> None:
    frontend_ports = FakeFrontendPorts()
    server, _hub, runner = new_web_adapter(frontend_ports, port=0)
    await server.start()
    try:
        async with signed_in(server) as client:
            forged = await client.post("/api/turns", json={"text": "rm -rf"}, headers={"Origin": "http://evil.example"})
            assert forged.status_code == 403
            assert forged.json() == {"error": "cross-origin request refused"}

            same_origin = await client.post(
                "/api/turns", json={"text": "hello"}, headers={"Origin": f"http://127.0.0.1:{server.port}"}
            )
            assert same_origin.status_code == 202
        await runner.wait()
        assert frontend_ports.queries == ["hello"]
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_a_rebinding_host_is_refused_even_with_the_cookie() -> None:
    """A page on attacker.example that rebinds its name to 127.0.0.1 sends its own Host."""
    server, hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await server.start()
    try:
        for path in ("/api/snapshot", "/api/events", "/"):
            head = await raw_head(
                server,
                f"GET {path} HTTP/1.1\r\nHost: attacker.example:{server.port}\r\n"
                f"Cookie: {cookie_header(server)}\r\n\r\n".encode(),
            )
            assert head.startswith(b"HTTP/1.1 403 Forbidden\r\n"), (path, head)
        assert hub.subscribers == 0
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_each_adapter_draws_its_own_token() -> None:
    first, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    second, _hub, _runner = new_web_adapter(FakeFrontendPorts(), port=0)
    await first.start()
    await second.start()
    try:
        assert first.address.rsplit("token=", 1)[1] != second.address.rsplit("token=", 1)[1]
        # One launch's cookie opens nothing on another, even under the other's name.
        stale = cookie_header(first).replace(f"super_agent_{first.port}=", f"super_agent_{second.port}=")
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{second.port}", timeout=5) as client:
            response = await client.get("/api/snapshot", headers={"Cookie": stale})
            assert response.status_code == 401
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_serve_prints_the_address_with_the_token_exactly_once(capsys: pytest.CaptureFixture[str]) -> None:
    task = asyncio.create_task(serve(FakeFrontendPorts(), port=0))
    captured = ""
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while ADDRESS_LINE.search(captured) is None:
            assert not task.done(), task
            assert loop.time() < deadline, f"serve never printed its address: {captured!r}"
            await asyncio.sleep(0.01)
            captured += capsys.readouterr().err
        match = ADDRESS_LINE.search(captured)
        assert match is not None
        address, port = match.group(1), match.group(2)

        # The printed address is the way in.
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            exchange = await client.get(address)
            assert exchange.status_code == 303
            assert (await client.get("/api/health")).status_code == 200
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        captured += capsys.readouterr().err

    assert len(captured.splitlines()) == 1, captured
    token = ADDRESS_LINE.search(captured)
    assert token is not None
    assert captured.count(token.group(3)) == 1
