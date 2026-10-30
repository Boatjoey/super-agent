"""Execution errors survive independent persistence, delivery, and telemetry failures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from super_agent import store
from super_agent.errors import JoinedError, errors_is
from super_agent.runtime import machine
from super_agent.runtime.engine import new_engine, new_engine_with_executor
from super_agent.runtime.execution import DefaultScheduledActionExecutor, ScheduledActionInput, ScheduledActionResult
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.protocol.types import ModelResponse, StreamChunk, ToolSpec
from super_agent.runtime.session import (
    ErrorPersistenceFailed,
    Metadata,
    Session,
    SessionError,
    SessionID,
    SessionNotification,
    StateChanged,
)
from super_agent.runtime.telemetry import telemetry
from super_agent.store import telemetry as store_telemetry
from tests.fakes.execution import FakeToolRunner
from tests.fakes.model import ScriptedModel


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("persist_fails", [False, True])
def test_execution_error_is_preserved_when_reporting_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool, persist_fails: bool
) -> None:
    repository = store.new_repository(store.new(str(tmp_path / "store")))
    meta = repository.create(Metadata(), [])
    session = Session(new_engine(None, None, None), repository=repository, meta=meta)
    original = RuntimeError("tool action failed")
    persistence_failure = OSError("cannot save error")
    saved: list[BaseException] = []
    records: list[tuple[str, Mapping[str, object]]] = []
    save_error = repository.save_error

    def persist(session_id: SessionID, failure: BaseException) -> None:
        saved.append(failure)
        if persist_fails:
            raise persistence_failure
        save_error(session_id, failure)

    def record(kind: str, fields: Mapping[str, object]) -> None:
        records.append((kind, fields))

    monkeypatch.setattr(repository, "save_error", persist)
    monkeypatch.setattr(telemetry, "record", record)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue(maxsize=1)
    if full:
        queue.put_nowait(StateChanged(state=machine.STATE_IDLE))

    result = session.failTurn(queue, original)

    assert saved == [original]
    assert errors_is(result, original)
    if persist_fails:
        assert isinstance(result, JoinedError)
        assert result.members[0] is original
        assert result.__cause__ is original
        secondary = result.members[1]
        assert isinstance(secondary, ErrorPersistenceFailed)
        assert secondary.__cause__ is persistence_failure
        assert errors_is(result, persistence_failure)
    else:
        assert result is original
        assert len(repository.load_audit_events(meta.id)) == 1
    if full:
        assert not any(isinstance(queue.get_nowait(), SessionError) for _ in range(queue.qsize()))
    else:
        notification = queue.get_nowait()
        assert isinstance(notification, SessionError)
        assert notification.err is original
    assert [kind for kind, _ in records] == [
        *(["error_persistence_failed"] if persist_fails else []),
        *(["error_notification_dropped"] if full else []),
    ]


@pytest.mark.parametrize("persist_fails", [False, True])
def test_telemetry_failure_cannot_replace_execution_or_persistence_error(
    monkeypatch: pytest.MonkeyPatch, persist_fails: bool
) -> None:
    session = Session(new_engine(None, None, None))
    original = ValueError("execution failed")
    saved: list[BaseException | None] = []
    persistence_failure = OSError("storage failed")

    def persist(failure: BaseException | None) -> None:
        saved.append(failure)
        if persist_fails:
            raise persistence_failure

    def record(kind: str, fields: Mapping[str, object]) -> None:
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(session, "persistError", persist)
    monkeypatch.setattr(telemetry, "record", record)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue(maxsize=1)
    queue.put_nowait(StateChanged(state=machine.STATE_IDLE))
    result = session.failTurn(queue, original)
    assert saved == [original]
    assert errors_is(result, original)
    assert errors_is(result, persistence_failure) == persist_fails
    if not persist_fails:
        assert result is original


def test_disconnected_notification_sink_is_reported_without_masking_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Session(new_engine(None, None, None))
    original = RuntimeError("execution failed")
    notification_failure = ConnectionError("frontend disconnected")
    saved: list[BaseException | None] = []
    monkeypatch.setattr(session, "persistError", saved.append)

    class Disconnected(asyncio.Queue[SessionNotification]):
        def put_nowait(self, item: SessionNotification) -> None:
            raise notification_failure

    result = session.failTurn(Disconnected(), original)
    assert saved == [original]
    assert isinstance(result, JoinedError)
    assert result.members == (original, notification_failure)
    assert result.__cause__ is original


@pytest.mark.asyncio
async def test_tool_action_failure_is_saved_and_returned_when_notifications_are_full(tmp_path: Path) -> None:
    """Exercise an executor fault while running a tool, with real error persistence.

    Ordinary tool exceptions are intentionally returned to the model as tool
    results; an execution fault is what drives the session's failure path.
    """
    original = RuntimeError("tool action execution failed")

    class FaultingExecutor(DefaultScheduledActionExecutor):
        async def execute(
            self,
            ctx: RunContext,
            action: machine.ScheduledAction,
            env: ScheduledActionInput,
            chunk_func: Callable[[StreamChunk], None],
        ) -> ScheduledActionResult:
            if isinstance(action, machine.RunTool):
                raise original
            return await super().execute(ctx, action, env, chunk_func)

    repository = store.new_repository(store.new(str(tmp_path / "store")))
    meta = repository.create(Metadata(), [])
    model = ScriptedModel(
        [ModelResponse(tool_calls=(machine.ToolCall(id="call-1", name="bash", input='{"command":"pwd"}'),))]
    )
    tools = FakeToolRunner(specs=(ToolSpec(name="bash"),))
    engine = new_engine_with_executor(FaultingExecutor(model, tools), None)
    await engine.ready()
    session = Session(engine, repository=repository, meta=meta)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue(maxsize=1)
    queue.put_nowait(StateChanged(state=machine.STATE_IDLE))
    log_path = tmp_path / "telemetry.jsonl"
    store_telemetry.configure(str(log_path))
    task = asyncio.create_task(session.run_turn(live_context(), "run tool", queue, asyncio.Queue()))
    try:
        async with asyncio.timeout(3):
            # All scripted actions run without yielding until notification drain.
            await asyncio.sleep(0)
            errors = [event.error for event in repository.load_audit_events(meta.id) if event.type == "error"]
            assert errors == [str(original)]
            while not task.done():
                if not queue.empty():
                    queue.get_nowait()
                await asyncio.sleep(0)
            with pytest.raises(RuntimeError) as raised:
                await task
            assert raised.value is original
        assert '"kind":"error_notification_dropped"' in log_path.read_text()
        assert '"error_type":"QueueFull"' in log_path.read_text()
        assert engine.state() == machine.STATE_IDLE
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await session.emitter.stop_delivery()
        store_telemetry.close()
