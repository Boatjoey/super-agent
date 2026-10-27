"""The ACP agent, driven by messages instead of a pipe.

Each test is one conversation between a client and the agent: send a message, read
what came back. The protocol's surface is entirely in those messages, so no
subprocess, no timing, and no editor is involved.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from super_agent import frontend
from super_agent.acp import AcpAgent, Connection, jsonrpc
from tests.fakes.frontend import AwaitingConversation, FakeConversation


class FakeClient:
    """Records what the agent sends, and answers permission requests on demand."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.permission_asked = asyncio.Event()

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if message.get("method") == "session/request_permission":
            self.permission_asked.set()

    def sent(self, method: str) -> list[dict[str, Any]]:
        return [message for message in self.messages if message.get("method") == method]

    def updates(self) -> list[dict[str, Any]]:
        return [message["params"]["update"] for message in self.sent("session/update")]

    def response(self, request_id: int | str) -> dict[str, Any]:
        for message in self.messages:
            if message.get("id") == request_id and "method" not in message:
                return message
        raise AssertionError(f"no response for {request_id}: {self.messages}")


def build(conversation: FakeConversation, session_id: str = "session-1") -> tuple[AcpAgent, FakeClient]:
    client = FakeClient()
    return AcpAgent(conversation, Connection(client.send), session_id=session_id), client


async def wait_for(predicate: Any, timeout: float = 5.0) -> None:
    """Wait until ``predicate()`` is true, without sleeping a fixed time."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the expected message never arrived")


@pytest.mark.asyncio
async def test_initialize_reports_the_protocol_and_its_capabilities() -> None:
    agent, client = build(FakeConversation())

    await agent.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
    await wait_for(lambda: client.messages)

    result = client.response(1)["result"]
    assert result["protocolVersion"] == 1
    assert result["agentCapabilities"]["loadSession"] is True
    assert result["agentCapabilities"]["promptCapabilities"]["image"] is False
    assert result["authMethods"] == []


@pytest.mark.asyncio
async def test_session_new_answers_with_the_session_and_its_modes() -> None:
    agent, client = build(FakeConversation(mode="ask"))

    await agent.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/work", "mcpServers": []}}
    )
    await wait_for(lambda: client.messages)

    result = client.response(2)["result"]
    assert result["sessionId"] == "session-1"
    assert result["modes"]["currentModeId"] == "ask"
    assert [mode["id"] for mode in result["modes"]["availableModes"]] == ["ask", "accept-edits", "plan", "bypass"]


@pytest.mark.asyncio
async def test_a_prompt_streams_only_what_is_new() -> None:
    """The contract reports the whole message each time; the protocol wants deltas."""
    conversation = FakeConversation(
        notifications=[
            frontend.StreamChunkReceived(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="Hel")),
            frontend.StreamChunkReceived(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="Hello")),
            frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="Hello")),
        ]
    )
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "hi"}]}}
    )
    await wait_for(lambda: any(message.get("id") == 3 and "method" not in message for message in client.messages))

    assert conversation.queries == ["hi"]
    assert client.response(3)["result"] == {"stopReason": "end_turn"}
    assert [update["content"]["text"] for update in client.updates()] == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_reasoning_arrives_as_thought_chunks() -> None:
    conversation = FakeConversation(
        notifications=[
            frontend.StreamChunkReceived(
                message=frontend.Message(role=frontend.ROLE_ASSISTANT, reasoning_content="think")
            ),
        ]
    )
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "hi"}]}}
    )
    await wait_for(lambda: any(message.get("id") == 4 and "method" not in message for message in client.messages))

    kinds = [update["sessionUpdate"] for update in client.updates()]
    assert kinds == ["agent_thought_chunk"]
    assert client.updates()[0]["content"]["text"] == "think"


@pytest.mark.asyncio
async def test_tool_calls_and_results_become_tool_call_updates() -> None:
    call = frontend.ToolCall(id="call-1", name="run_command", input='{"command": "ls -la"}')
    conversation = FakeConversation(
        notifications=[
            frontend.MessageAppended(
                message=frontend.Message(role=frontend.ROLE_ASSISTANT, tool_calls=(call,)),
            ),
            frontend.MessageAppended(
                message=frontend.Message(
                    role=frontend.ROLE_TOOL, tool_call_id="call-1", tool_name="run_command", content="total 0"
                ),
            ),
        ]
    )
    agent, client = build(conversation)

    await agent.handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "session/prompt",
            "params": {"prompt": [{"type": "text", "text": "list"}]},
        }
    )
    await wait_for(lambda: any(message.get("id") == 5 and "method" not in message for message in client.messages))

    updates = client.updates()
    assert updates[0]["sessionUpdate"] == "tool_call"
    assert updates[0]["toolCallId"] == "call-1"
    assert updates[0]["kind"] == "execute"
    assert "ls -la" in updates[0]["title"]
    assert updates[1] == {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "call-1",
        "status": "completed",
        "content": [{"type": "content", "content": {"type": "text", "text": "total 0"}}],
    }


@pytest.mark.asyncio
async def test_a_permission_request_carries_the_tool_and_three_options() -> None:
    conversation = AwaitingConversation()
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 6, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "run"}]}}
    )
    await asyncio.wait_for(client.permission_asked.wait(), timeout=5)

    asked = client.sent("session/request_permission")[0]
    params = asked["params"]
    assert params["sessionId"] == "session-1"
    assert params["toolCall"]["toolCallId"] == "call-1"
    assert params["toolCall"]["kind"] == "execute"
    assert "writes files" in params["toolCall"]["title"]
    assert [option["optionId"] for option in params["options"]] == ["allow_once", "allow_always", "reject_once"]

    await agent.handle(
        {"jsonrpc": "2.0", "id": asked["id"], "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}}}
    )
    await wait_for(lambda: any(message.get("id") == 6 and "method" not in message for message in client.messages))

    assert conversation.decision == "once"
    assert client.response(6)["result"] == {"stopReason": "end_turn"}


@pytest.mark.asyncio
async def test_a_rejected_permission_denies_and_a_cancelled_one_denies_too() -> None:
    conversation = AwaitingConversation()
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 7, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "run"}]}}
    )
    await asyncio.wait_for(client.permission_asked.wait(), timeout=5)
    asked = client.sent("session/request_permission")[0]

    await agent.handle({"jsonrpc": "2.0", "id": asked["id"], "result": {"outcome": {"outcome": "cancelled"}}})
    await wait_for(lambda: any(message.get("id") == 7 and "method" not in message for message in client.messages))

    assert conversation.decision == "deny"


@pytest.mark.asyncio
async def test_cancel_ends_the_prompt_with_a_cancelled_stop_reason() -> None:
    conversation = AwaitingConversation()
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 8, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "run"}]}}
    )
    await asyncio.wait_for(client.permission_asked.wait(), timeout=5)

    await agent.handle({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "session-1"}})
    await wait_for(lambda: any(message.get("id") == 8 and "method" not in message for message in client.messages))

    assert client.response(8)["result"] == {"stopReason": "cancelled"}
    assert conversation.cancellations == 1


@pytest.mark.asyncio
async def test_a_failed_turn_is_an_error_response_not_an_empty_answer() -> None:
    conversation = FakeConversation(
        error=frontend.Failure(message="provider refused", code=frontend.FAILED, operation="run_turn")
    )
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 9, "method": "session/prompt", "params": {"prompt": [{"type": "text", "text": "hi"}]}}
    )
    await wait_for(lambda: any(message.get("id") == 9 and "method" not in message for message in client.messages))

    failure = client.response(9)["error"]
    assert failure == {"code": jsonrpc.INTERNAL_ERROR, "message": "provider refused"}


@pytest.mark.asyncio
async def test_an_empty_prompt_is_refused_before_the_turn_starts() -> None:
    conversation = FakeConversation()
    agent, client = build(conversation)

    await agent.handle(
        {"jsonrpc": "2.0", "id": 10, "method": "session/prompt", "params": {"prompt": [{"type": "image"}]}}
    )
    await wait_for(lambda: client.messages)

    assert client.response(10)["error"]["code"] == jsonrpc.INVALID_PARAMS
    assert conversation.queries == []


@pytest.mark.asyncio
async def test_an_unknown_method_is_reported_as_such() -> None:
    agent, client = build(FakeConversation())

    await agent.handle({"jsonrpc": "2.0", "id": 11, "method": "session/teleport", "params": {}})
    await wait_for(lambda: client.messages)

    assert client.response(11)["error"]["code"] == jsonrpc.METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_load_resumes_an_existing_session_and_replays_it() -> None:
    conversation = FakeConversation(
        view=frontend.ConversationView(
            messages=(
                frontend.Message(role=frontend.ROLE_USER, content="earlier question"),
                frontend.Message(role=frontend.ROLE_ASSISTANT, content="earlier answer"),
            )
        )
    )
    agent, client = build(conversation)

    await agent.handle(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "session/load",
            "params": {"sessionId": "saved-9", "cwd": "/w", "mcpServers": []},
        }
    )
    await wait_for(lambda: any(message.get("id") == 12 and "method" not in message for message in client.messages))

    assert conversation.resumes == ["saved-9"]
    assert agent.session_id == "saved-9"
    kinds = [update["sessionUpdate"] for update in client.updates()]
    assert kinds == ["user_message_chunk", "agent_message_chunk"]
    assert client.updates()[0]["content"]["text"] == "earlier question"


@pytest.mark.asyncio
async def test_set_mode_changes_the_permission_mode_and_rejects_an_unknown_one() -> None:
    conversation = FakeConversation(mode="ask")
    agent, client = build(conversation)

    await agent.handle({"jsonrpc": "2.0", "id": 13, "method": "session/set_mode", "params": {"modeId": "accept-edits"}})
    await wait_for(lambda: client.messages)
    assert conversation.modes == ["accept-edits"]
    assert client.response(13)["result"]["modes"]["currentModeId"] == "accept-edits"

    await agent.handle({"jsonrpc": "2.0", "id": 14, "method": "session/set_mode", "params": {"modeId": "sudo"}})
    await wait_for(lambda: any(message.get("id") == 14 for message in client.messages))
    assert client.response(14)["error"]["code"] == jsonrpc.INVALID_PARAMS


@pytest.mark.asyncio
async def test_a_response_to_an_unknown_request_is_ignored() -> None:
    """A late or duplicated answer must not resurrect a finished turn."""
    agent, client = build(FakeConversation())

    await agent.handle({"jsonrpc": "2.0", "id": 999, "result": {}})

    assert client.messages == []
