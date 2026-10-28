"""The web transport against the real adapter.

The web route tests use a fake port, which proves the transport; this one proves
the other half — that :class:`ConversationAdapter` actually satisfies the
contract that transport calls, with a real engine underneath.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from super_agent import frontend, runtime, workspace
from super_agent.app import new_conversation_adapter
from super_agent.app.conversation_adapter import to_frontend_message
from super_agent.web import EventHub, Request, Router, TurnRunner
from tests.fakes.execution import FakeToolRunner
from tests.fakes.model import GateModel, ScriptedModel


async def build_conversation() -> tuple[frontend.Conversation, str]:
    model = ScriptedModel([runtime.ModelResponse(content="hello from the engine")])
    engine = runtime.new_engine(model, None, None)
    await engine.ready()
    session = runtime.new_session(engine)
    return new_conversation_adapter(session), str(session.metaID())


@pytest.mark.asyncio
async def test_the_web_transport_drives_the_real_adapter_for_one_turn() -> None:
    conversation, _session_id = await build_conversation()
    hub = EventHub()
    runner = TurnRunner(conversation, hub)
    router = Router(conversation, runner, hub)
    subscription = router.subscribe()

    response = await router.handle(
        Request(method="POST", path="/api/turns", body=json.dumps({"text": "hi"}).encode("utf-8"))
    )
    assert response.status == 202
    await runner.wait()

    events: list[dict[str, Any]] = [await asyncio.wait_for(subscription.get(), timeout=5)]
    while events[-1]["kind"] != "TurnFinished":
        events.append(await asyncio.wait_for(subscription.get(), timeout=5))
    events.append(await asyncio.wait_for(subscription.get(), timeout=5))

    kinds = [event["kind"] for event in events]
    assert "MessageAppended" in kinds
    assert kinds[-1] == "Snapshot"
    appended = [event["message"]["content"] for event in events if event["kind"] == "MessageAppended"]
    assert "hello from the engine" in appended
    assert events[-1]["snapshot"]["agent_status"]["label"] == "Idle"


@pytest.mark.asyncio
async def test_the_adapter_runs_a_queued_input_as_the_next_turn() -> None:
    """One submission, two turns: sequencing is the application's, not the caller's.

    A browser submits once; when an input is queued while that
    submission runs, the adapter starts the next turn itself and reports the
    acceptance on the same stream. A transport therefore never has to know that a
    queue exists.
    """
    release = asyncio.Event()
    model = GateModel(
        release,
        [runtime.ModelResponse(content="first"), runtime.ModelResponse(content="second")],
    )
    engine = runtime.new_engine(model, None, None)
    await engine.ready()
    conversation = new_conversation_adapter(runtime.new_session(engine))
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()

    turn = asyncio.create_task(conversation.run_turn("hi", notifications, frontend.Cancellation()))
    await asyncio.wait_for(model.started.wait(), timeout=5)
    receipt = await conversation.queue("then run the tests")
    assert receipt.status == frontend.QUEUED
    release.set()
    error = await asyncio.wait_for(turn, timeout=5)

    assert error is None
    seen: list[frontend.ConversationNotification] = []
    while (notification := await notifications.get()) is not None:
        seen.append(notification)

    assert [item for item in seen if isinstance(item, frontend.QueuedInputAccepted)] == [
        frontend.QueuedInputAccepted(input_id=receipt.input_id, turn=2)
    ]
    appended = [item.message.content for item in seen if isinstance(item, frontend.MessageAppended)]
    assert appended == ["hi", "first", "then run the tests", "second"]


@pytest.mark.asyncio
async def test_queueing_with_nothing_running_is_refused_as_a_value() -> None:
    """The common race — the turn ended first — is answered, not raised."""
    conversation, _session_id = await build_conversation()

    receipt = await conversation.queue("too late")

    assert receipt.status == frontend.REJECTED
    assert receipt.reason == "no turn is running"


# --- approvals across the boundary -------------------------------------------


async def next_approval(notifications: frontend.Channel[frontend.ConversationNotification]) -> Any:
    """Read notifications until an approval request arrives."""
    while True:
        notification = await asyncio.wait_for(notifications.get(), timeout=5)
        if isinstance(notification, frontend.ToolApprovalRequested):
            return notification


async def build_approval_conversation() -> frontend.Conversation:
    """One risky tool call, so the turn has to stop and ask."""
    model = ScriptedModel(
        [
            runtime.ModelResponse(tool_calls=(runtime.ToolCall(id="call-1", name="bash", input="printf ok"),)),
            runtime.ModelResponse(content="done"),
        ]
    )
    tools = FakeToolRunner(results={"bash": "ok"}, specs=(runtime.ToolSpec(name="bash", risky=True),))
    engine = runtime.new_engine(model, tools, None)
    await engine.ready()
    return new_conversation_adapter(runtime.new_session(engine))


@pytest.mark.asyncio
async def test_an_approval_request_is_named_and_is_the_one_in_the_snapshot() -> None:
    """The id a front end answers with comes from the application, not from luck.

    An event carries it, and a snapshot taken while the turn waits carries the
    same one — otherwise a tab that reconnected mid-approval could not answer.
    """
    conversation = await build_approval_conversation()
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()
    turn = asyncio.create_task(conversation.run_turn("run it", notifications, frontend.Cancellation()))

    request = await next_approval(notifications)

    assert request.request_id.startswith("approval-")
    assert conversation.snapshot().pending_approval_id == request.request_id

    receipt = await conversation.approve(frontend.APPROVE_ONCE, request.request_id)
    assert receipt.status == frontend.ACCEPTED
    assert await asyncio.wait_for(turn, timeout=5) is None


@pytest.mark.asyncio
async def test_an_answer_to_another_request_is_refused_and_leaves_the_turn_waiting() -> None:
    """A stale click must not run the tool: the refusal says which request it named."""
    conversation = await build_approval_conversation()
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()
    turn = asyncio.create_task(conversation.run_turn("run it", notifications, frontend.Cancellation()))
    request = await next_approval(notifications)

    refused = await conversation.approve(frontend.APPROVE_ONCE, "approval-somewhere-else")
    assert refused.status == frontend.REJECTED
    assert refused.reason == "that request is no longer pending"
    assert conversation.snapshot().pending_approval_id == request.request_id

    accepted = await conversation.approve(frontend.DENY, request.request_id)
    assert accepted.status == frontend.ACCEPTED
    assert await asyncio.wait_for(turn, timeout=5) is None


@pytest.mark.asyncio
async def test_the_same_answer_twice_only_counts_once() -> None:
    """A second click on the same prompt is the ordinary way a decision repeats."""
    conversation = await build_approval_conversation()
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()
    turn = asyncio.create_task(conversation.run_turn("run it", notifications, frontend.Cancellation()))
    request = await next_approval(notifications)

    first = await conversation.approve(frontend.DENY, request.request_id)
    second = await conversation.approve(frontend.APPROVE_ONCE, request.request_id)

    assert first.status == frontend.ACCEPTED
    assert second.status == frontend.REJECTED
    assert await asyncio.wait_for(turn, timeout=5) is None


@pytest.mark.asyncio
async def test_an_answer_with_no_turn_running_is_refused_by_value() -> None:
    conversation, _session_id = await build_conversation()

    receipt = await conversation.approve(frontend.APPROVE_ONCE, "approval-1")

    assert receipt.status == frontend.REJECTED
    assert receipt.reason == "no turn is running"


# --- failure and configuration values ----------------------------------------


@pytest.mark.asyncio
async def test_a_failed_turn_comes_back_as_a_value_a_front_end_can_show() -> None:
    """No exception type to inspect: the message, the code, and the operation."""
    model = ScriptedModel([])  # exhausting the script raises inside the turn
    engine = runtime.new_engine(model, None, None)
    await engine.ready()
    conversation = new_conversation_adapter(runtime.new_session(engine))
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()

    failure = await conversation.run_turn("hi", notifications, frontend.Cancellation())

    assert failure is not None
    assert failure.code == frontend.FAILED
    assert failure.operation == "run_turn"
    assert failure.message


@pytest.mark.asyncio
async def test_the_configuration_view_describes_this_application() -> None:
    conversation, session_id = await build_conversation()

    config = conversation.config_view()

    assert config.session_id == session_id
    assert "turn" in config.capabilities
    assert "approve" in config.capabilities
    # No controller was passed, so the capabilities that need one are absent: a
    # browser must not offer a button whose call would fail.
    assert "mcp" not in config.capabilities
    # Nothing exposes a reasoning level yet, so the field stays empty rather than
    # invented.
    assert config.reasoning_effort == ""


@pytest.mark.asyncio
async def test_the_configuration_view_reads_the_workspace_it_belongs_to(tmp_path: Path) -> None:
    """The view is read back through the port's spec, not a concrete object's helpers."""
    root = str(tmp_path)
    spec = runtime.WorkspaceSpec(
        primary_root=root,
        cwd=root,
        roots=(runtime.WorkspaceRootSpec(path=root, access=runtime.WorkspaceAccessMode("read_write")),),
    )
    engine = runtime.new_engine(ScriptedModel([]), None, None)
    await engine.ready()
    session = runtime.new_persistent_session(
        engine,
        None,
        workspace.new(workspace.contextFromSpec(spec)),
        runtime.Metadata(
            id=runtime.SessionID("session-with-workspace"),
            title="ws",
            cwd=root,
            instruction_sources=("AGENTS.md",),
        ),
    )

    config = new_conversation_adapter(session).config_view()

    assert Path(config.workspace) == tmp_path.resolve()
    assert tuple(Path(item) for item in config.roots) == (tmp_path.resolve(),)
    assert config.session_title == "ws"
    assert config.instruction_sources == ("AGENTS.md",)


def test_a_message_with_an_attachment_reaches_the_transcript() -> None:
    """The conversion names the attachment type the contract exports.

    It previously named one that does not exist, which only fails on the path
    that carries an attachment — a session with an attached file would have
    crashed the snapshot rather than showing it.
    """
    message = runtime.Message(
        role=runtime.Role("user"),
        content="look",
        attachments=(runtime.Attachment(name="notes.txt", mime="text/plain"),),
    )

    rendered = to_frontend_message(message)

    assert rendered.attachments == (frontend.Attachment(name="notes.txt", mime="text/plain"),)
