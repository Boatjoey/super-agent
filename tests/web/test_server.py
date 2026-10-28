"""The HTTP transport itself: one real socket, one real stream.

The route table is tested without a socket; this file tests only what the socket
adds — request framing, the static files, and the one connection that stays open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import cast

import httpx
import pytest

from super_agent import frontend
from super_agent.web import new_server
from super_agent.web.server import _read_request  # pyright: ignore[reportPrivateUsage]
from tests.fakes.frontend import FakeConversation


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
    conversation = FakeConversation(
        agents=[frontend.AgentSummary(name="build", provider="deepseek", model="deepseek-chat", permission_mode="ask")]
    )
    server, _hub, _runner = new_server(conversation, port=0)
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
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
    conversation = FakeConversation(
        notifications=[
            frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="hi")),
        ]
    )
    server, hub, runner = new_server(conversation, port=0)
    await server.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    try:
        writer.write(b"GET /api/events HTTP/1.1\r\nHost: localhost\r\nAccept: text/event-stream\r\n\r\n")
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert b"200 OK" in head
        assert b"text/event-stream" in head

        name, payload = await read_event(reader)
        assert name == "Snapshot"
        snapshot = cast("dict[str, object]", payload["snapshot"])
        agent_status = cast("dict[str, object]", snapshot["agent_status"])
        assert agent_status["label"] == "Idle"

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
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
    server, _hub, _runner = new_server(FakeConversation(), port=0)
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
    server, _hub, _runner = new_server(FakeConversation(), port=0)
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.port}", timeout=5) as client:
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
