"""The stdio framing: newline-delimited JSON in, the same out.

The transport is tested with in-memory streams, so the only thing under test is
the framing and the fact that a batch of messages is fully answered before end of
input ends the process.
"""

from __future__ import annotations

import io
import json

import pytest

from super_agent import frontend
from super_agent.acp import serve_streams
from tests.fakes.frontend import FakeConversation


def lines(output: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_a_batch_of_messages_is_framed_and_answered() -> None:
    conversation = FakeConversation(
        notifications=[frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="ok"))]
    )
    stdin = io.BytesIO(
        b'{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}\n'
        b'{"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/w"}}\n'
        b'{"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "hi"}]}}\n'
    )
    stdout = io.StringIO()

    await serve_streams(conversation, session_id="s-1", stdin=stdin, stdout=stdout)

    messages = lines(stdout)
    responses = {message["id"]: message for message in messages if "method" not in message}
    assert responses[1]["result"]["protocolVersion"] == 1
    assert responses[2]["result"]["sessionId"] == "s-1"
    assert responses[3]["result"] == {"stopReason": "end_turn"}
    assert any(message.get("method") == "session/update" for message in messages)


@pytest.mark.asyncio
async def test_invalid_json_is_answered_and_the_stream_continues() -> None:
    stdin = io.BytesIO(
        b'not json\n{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}\n'
    )
    stdout = io.StringIO()

    await serve_streams(FakeConversation(), session_id="s-1", stdin=stdin, stdout=stdout)

    messages = lines(stdout)
    assert messages[0]["error"]["code"] == -32700
    assert messages[1]["id"] == 1
    assert "result" in messages[1]


@pytest.mark.asyncio
async def test_blank_lines_are_not_messages() -> None:
    stdin = io.BytesIO(b"\n\n   \n")
    stdout = io.StringIO()

    await serve_streams(FakeConversation(), session_id="s-1", stdin=stdin, stdout=stdout)

    assert lines(stdout) == []
