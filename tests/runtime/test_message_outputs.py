"""Durability and notification progress survive congestion and independent failures."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from super_agent import store
from super_agent.errors import JoinedError
from super_agent.runtime import machine
from super_agent.runtime.engine import new_engine
from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ToolSpec
from super_agent.runtime.session import MessageAppended, Metadata, Session, SessionID, SessionNotification, StateChanged
from tests.fakes.execution import FakeToolRunner
from tests.fakes.model import ScriptedModel


def outputs(tmp_path: Path, messages: list[machine.Message]) -> tuple[Session, store.Repository, Metadata]:
    repository = store.new_repository(store.new(str(tmp_path / "store")))
    meta = repository.create(Metadata(), [])
    engine = new_engine(None, None, messages)
    return Session(engine, repository=repository, meta=meta), repository, meta


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tool", [False, True])
async def test_full_notification_queue_does_not_block_commits_or_persistence(tmp_path: Path, with_tool: bool) -> None:
    session, repository, meta = outputs(tmp_path, [])
    responses = [machine.ModelResponse(content="done")]
    expected = ["hello", "done"]
    if with_tool:
        responses.insert(
            0,
            machine.ModelResponse(tool_calls=(machine.ToolCall(id="call-1", name="bash", input='{"command":"pwd"}'),)),
        )
        expected = ["hello", "", "tool output", "done"]
    tools = FakeToolRunner(results={"bash": "tool output"}, specs=(ToolSpec(name="bash"),))
    session.engine = new_engine(ScriptedModel(responses), tools, [])
    await session.engine.ready()
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue(maxsize=1)
    queue.put_nowait(StateChanged(state=machine.STATE_IDLE))
    task = asyncio.create_task(session.run_turn(live_context(), "hello", queue, asyncio.Queue()))
    try:
        # Scripted ports and snapshot capture do not yield; the next suspension
        # point is notification drain, after the engine has completed all work.
        await asyncio.sleep(0)
        assert session.engine.state() == machine.STATE_IDLE
        assert [m.content for m in repository.load(meta.id)[0]] == expected
        assert len(tools.calls) == int(with_tool)
        assert not task.done()
        seen: list[SessionNotification] = []
        async with asyncio.timeout(2):
            while not task.done():
                if not queue.empty():
                    seen.append(queue.get_nowait())
                await asyncio.sleep(0)
            await task
        while not queue.empty():
            seen.append(queue.get_nowait())
        assert [item.message.content for item in seen if isinstance(item, MessageAppended)] == expected
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await session.emitter.stop_delivery()


@pytest.mark.asyncio
@pytest.mark.parametrize("after_append", [False, True])
async def test_uncertain_message_write_is_reconciled_without_duplicate_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_append: bool
) -> None:
    messages = [machine.Message(role=machine.ROLE_USER, content="same")] * 2
    messages.append(machine.Message(role=machine.ROLE_ASSISTANT, content="done"))
    session, repository, meta = outputs(tmp_path, messages)
    save = repository.save_message
    attempts = 0
    failure = OSError("uncertain append")

    def flaky_save(session_id: SessionID, message: machine.Message) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            if after_append:
                save(session_id, message)
            raise failure
        save(session_id, message)

    monkeypatch.setattr(repository, "save_message", flaky_save)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue()
    with pytest.raises(OSError) as raised:
        await session.emitSnapshot(queue)
    assert raised.value is failure
    assert session.message_persistence.persisted_count == 1
    assert session.emitter.emittedMessages == 3
    assert len(repository.load(meta.id)[0]) == (2 if after_append else 1)

    await session.emitSnapshot(queue)
    assert repository.load(meta.id)[0] == messages
    assert session.message_persistence.persisted_count == 3
    saved_attempts = attempts
    await session.emitSnapshot(queue)
    assert attempts == saved_attempts
    seen = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [item.message for item in seen if isinstance(item, MessageAppended)] == messages


@pytest.mark.asyncio
async def test_failed_reconciliation_never_blindly_retries_uncertain_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = machine.Message(role=machine.ROLE_USER, content="hello")
    session, repository, meta = outputs(tmp_path, [message])
    save = repository.save_message
    load = repository.load
    attempts = 0

    def uncertain_save(session_id: SessionID, value: machine.Message) -> None:
        nonlocal attempts
        attempts += 1
        save(session_id, value)
        raise OSError("append acknowledged late")

    def broken_load(session_id: SessionID) -> tuple[list[machine.Message], Metadata]:
        raise OSError("reconciliation unavailable")

    monkeypatch.setattr(repository, "save_message", uncertain_save)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue()
    with pytest.raises(OSError, match="append acknowledged late"):
        await session.emitSnapshot(queue)
    monkeypatch.setattr(repository, "load", broken_load)
    with pytest.raises(OSError, match="reconciliation unavailable"):
        await session.emitSnapshot(queue)
    assert attempts == 1
    monkeypatch.setattr(repository, "load", load)
    await session.emitSnapshot(queue)
    assert attempts == 1
    assert load(meta.id)[0] == [message]


class BrokenNotificationQueue(asyncio.Queue[SessionNotification]):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def put_nowait(self, item: SessionNotification) -> None:
        raise self.failure


@pytest.mark.asyncio
async def test_notification_failure_does_not_repeat_persisted_messages(tmp_path: Path) -> None:
    messages = [machine.Message(role=machine.ROLE_USER, content="hello")]
    session, repository, meta = outputs(tmp_path, messages)
    failure = RuntimeError("notification consumer failed")
    with pytest.raises(RuntimeError) as raised:
        await session.emitSnapshot(BrokenNotificationQueue(failure))
    assert raised.value is failure
    assert repository.load(meta.id)[0] == messages
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue()
    await session.emitSnapshot(queue)
    assert repository.load(meta.id)[0] == messages
    seen = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [item.message for item in seen if isinstance(item, MessageAppended)] == messages


@pytest.mark.asyncio
async def test_message_and_notification_failures_are_both_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, repository, _meta = outputs(tmp_path, [machine.Message(role=machine.ROLE_USER, content="hello")])
    persistence_failure = OSError("repository failed")
    notification_failure = RuntimeError("notification failed")

    def fail_save(session_id: SessionID, message: machine.Message) -> None:
        raise persistence_failure

    monkeypatch.setattr(repository, "save_message", fail_save)
    with pytest.raises(JoinedError) as raised:
        await session.emitSnapshot(BrokenNotificationQueue(notification_failure))
    assert raised.value.members == (persistence_failure, notification_failure)


@pytest.mark.asyncio
async def test_background_delivery_failure_keeps_pending_messages_for_retry(tmp_path: Path) -> None:
    messages = [machine.Message(role=machine.ROLE_USER, content="hello")]
    session, repository, meta = outputs(tmp_path, messages)
    failure = RuntimeError("delivery failed after congestion")

    class FailedDelivery(asyncio.Queue[SessionNotification]):
        async def put(self, item: SessionNotification) -> None:
            raise failure

    queue = FailedDelivery(maxsize=1)
    queue.put_nowait(StateChanged(state=machine.STATE_IDLE))
    await session.emitSnapshot(queue)
    assert repository.load(meta.id)[0] == messages
    with pytest.raises(RuntimeError) as raised:
        await session.emitter.flush(queue)
    assert raised.value is failure
    retry: asyncio.Queue[SessionNotification] = asyncio.Queue()
    await session.emitSnapshot(retry)
    assert repository.load(meta.id)[0] == messages
    seen = [retry.get_nowait() for _ in range(retry.qsize())]
    assert [item.message for item in seen if isinstance(item, MessageAppended)] == messages


@pytest.mark.asyncio
async def test_history_mismatch_blocks_retry_instead_of_duplicating_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, repository, meta = outputs(tmp_path, [machine.Message(role=machine.ROLE_USER, content="hello")])

    def failed_save(session_id: SessionID, message: machine.Message) -> None:
        raise OSError("save failed")

    save = repository.save_message
    monkeypatch.setattr(repository, "save_message", failed_save)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue()
    with pytest.raises(OSError):
        await session.emitSnapshot(queue)
    save(meta.id, machine.Message(role=machine.ROLE_USER, content="different history"))
    monkeypatch.setattr(repository, "save_message", save)
    with pytest.raises(ValueError, match="stored message history"):
        await session.emitSnapshot(queue)
    assert [message.content for message in repository.load(meta.id)[0]] == ["different history"]
