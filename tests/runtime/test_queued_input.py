"""Queued input: an input submitted while a turn runs, for the *next* turn.

The runtime spec gives such an input to the turn after the one in flight, and
accepts it when that turn starts. That boundary is the point: unlike steering, the
input has to survive the end of the turn it was submitted under, or it could never
become a turn at all. These cases walk the boundary from both sides — the machine
alone, a real engine loop, and the notification stream a front end reads — because
the interesting failures (input applied to the wrong turn, input lost at the
boundary, acceptance reported twice) only show up when the three are wired
together.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence

import pytest

from super_agent.runtime import machine
from super_agent.runtime.engine import Engine, new_engine
from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ModelResponse, StreamChunk, ToolSpec
from super_agent.runtime.session import (
    NOTIFICATIONS_CLOSED,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    SessionNotification,
    new_session,
)

QUEUED_TEXT = "then run the tests"


def apply(data: machine.RuntimeData, event: machine.Event) -> machine.RuntimeData:
    """Commit one event the way the engine does: decide, apply, validate."""
    decision = machine.transition(machine.snapshot_from(data), event)
    return machine.DefaultRuntimeDataChangeApplier().apply_runtime_data_changes(data, decision).runtime_data


def running_turn() -> machine.RuntimeData:
    """A turn in ``WaitingLLM`` with step one open."""
    return apply(machine.RuntimeData(state=machine.STATE_IDLE), machine.UserMessageSubmitted(content="hi"))


def queued_pending() -> machine.RuntimeData:
    return apply(running_turn(), machine.InputQueued(content=QUEUED_TEXT, input_id="queue-1"))


def contents(data: machine.RuntimeData) -> list[str]:
    return [message.content for message in data.messages]


# --- where the input waits ---------------------------------------------------


def test_a_queued_input_is_held_without_joining_the_running_turn() -> None:
    """The turn in flight keeps its request, its step, and its transcript."""
    data = queued_pending()

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=1)
    assert contents(data) == ["hi"]
    assert data.queued == (machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),)


@pytest.mark.parametrize(
    "state",
    [
        machine.STATE_WAITING_LLM,
        machine.STATE_ADVANCING_QUEUE,
        machine.STATE_WAITING_APPROVAL,
        machine.STATE_RUNNING_TOOL,
    ],
    ids=["waiting-llm", "advancing-queue", "waiting-approval", "running-tool"],
)
def test_every_running_state_accepts_a_queued_input_without_changing_state(state: machine.State) -> None:
    event = machine.InputQueued(content=QUEUED_TEXT, input_id="queue-1")
    result = machine.transition(_snapshot_in(state), event)

    assert result.next_state == state
    assert result.runtime_data_changes == (
        machine.QueueInput(input=machine.QueuedInput(id="queue-1", content=QUEUED_TEXT)),
    )
    assert result.action_plan.schedule == ()


@pytest.mark.parametrize("state", [machine.STATE_IDLE, machine.STATE_INITIALIZING], ids=["idle", "initializing"])
def test_a_queued_input_cannot_ask_for_a_turn_of_its_own(state: machine.State) -> None:
    """With no turn to follow, the caller should start one instead."""
    with pytest.raises(machine.UnexpectedEventError):
        machine.transition(_snapshot_in(state), machine.InputQueued(content=QUEUED_TEXT, input_id="queue-1"))


def _snapshot_in(state: machine.State) -> machine.MachineSnapshot:
    call = machine.ToolCall(id="call-1", name="bash", input="pwd")
    if state == machine.STATE_ADVANCING_QUEUE:
        data = machine.RuntimeData(
            state=state, step=machine.Step(index=1), tool_batch=machine.ToolCallBatch(calls=[call])
        )
    elif state == machine.STATE_WAITING_APPROVAL:
        data = machine.RuntimeData(
            state=state,
            step=machine.Step(index=1),
            pending_tool=call,
            pending_permission=machine.PermissionRequest(),
            tool_batch=machine.ToolCallBatch(calls=[call], index=1),
        )
    elif state == machine.STATE_RUNNING_TOOL:
        data = machine.RuntimeData(
            state=state,
            step=machine.Step(index=1),
            current_tool=call,
            tool_batch=machine.ToolCallBatch(calls=[call], index=1),
        )
    elif state == machine.STATE_WAITING_LLM:
        data = machine.RuntimeData(state=state, step=machine.Step(index=1))
    else:
        data = machine.RuntimeData(state=state)
    return machine.snapshot_from(data)


# --- the turn boundary is the acceptance point --------------------------------


def test_the_next_turn_takes_the_input_up_and_names_itself() -> None:
    """Starting a turn with the input's id is what accepts it."""
    data = apply(queued_pending(), machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    # The first turn ended, and the input is still waiting: it belongs to the next
    # turn, not to the one that just finished.
    assert data.state == machine.STATE_IDLE
    assert contents(data) == ["hi", "done"]
    assert data.queued == (machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),)
    assert data.turn == 1

    data = apply(data, machine.UserMessageSubmitted(content=QUEUED_TEXT, input_id="queue-1"))

    assert data.state == machine.STATE_WAITING_LLM
    assert data.turn == 2
    assert data.step == machine.Step(index=1)
    assert contents(data) == ["hi", "done", QUEUED_TEXT]
    assert data.queued == ()


def test_acceptance_removes_only_the_input_that_turn_carries() -> None:
    data = apply(queued_pending(), machine.InputQueued(content="and update the docs", input_id="queue-2"))
    data = apply(data, machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    data = apply(data, machine.UserMessageSubmitted(content=QUEUED_TEXT, input_id="queue-1"))

    assert data.queued == (machine.QueuedInput(id="queue-2", content="and update the docs"),)


def test_an_id_that_names_nothing_still_starts_a_turn() -> None:
    """The input may have been discarded a moment earlier; the turn stands alone."""
    data = apply(queued_pending(), machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    data = apply(data, machine.UserMessageSubmitted(content="something else", input_id="queue-未"))

    assert contents(data) == ["hi", "done", "something else"]
    assert data.queued == (machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),)


def test_a_turn_submitted_without_an_id_leaves_the_queue_alone() -> None:
    data = apply(queued_pending(), machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    data = apply(data, machine.UserMessageSubmitted(content="unrelated"))

    assert data.queued == (machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),)


def test_an_idle_conversation_may_hold_a_queued_input() -> None:
    """Unlike steering, the queue is *meant* to outlive the turn it waited behind."""
    data = machine.RuntimeData(
        state=machine.STATE_IDLE,
        queued=(machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),),
    )

    machine.snapshot_from(data)  # does not raise


# --- a cancellation takes the queue with it, a failure does not ---------------


def test_a_cancellation_discards_what_was_queued_behind_it() -> None:
    data = apply(queued_pending(), machine.CancelRequested())

    assert data.state == machine.STATE_IDLE
    assert data.queued == ()
    assert QUEUED_TEXT not in contents(data)


def test_a_failure_keeps_the_queue_for_the_next_turn() -> None:
    """A failure ends the turn; it does not change what the user asked for next."""
    data = apply(queued_pending(), machine.ErrorOccurred(err=RuntimeError("boom")))

    assert data.state == machine.STATE_IDLE
    assert data.queued == (machine.QueuedInput(id="queue-1", content=QUEUED_TEXT),)


def test_a_reset_discards_the_queue_and_restarts_the_turn_number() -> None:
    data = apply(queued_pending(), machine.ResetRequested())

    assert data.queued == ()
    assert data.turn == 0


# --- the same behaviour through a real engine loop ---------------------------


class QueueingModel:
    """Replays responses and queues one input during a chosen model call."""

    def __init__(self, responses: Sequence[ModelResponse], *, submit_on_call: int = 0, submit: object = None) -> None:
        self.responses: list[ModelResponse] = list(responses)
        self.submit_on_call = submit_on_call
        self.submit = submit
        self.inputs: list[tuple[machine.Message, ...]] = []

    async def next(
        self,
        ctx: object,
        messages: list[machine.Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        self.inputs.append(tuple(messages))
        if len(self.inputs) - 1 == self.submit_on_call and callable(self.submit):
            await self.submit(QUEUED_TEXT)  # type: ignore[misc]
        return self.responses[len(self.inputs) - 1]


async def run_turn(engine: Engine, content: str, input_id: str = "") -> None:
    await engine.run_turn(live_context(), machine.UserMessageSubmitted(content=content, input_id=input_id), None, None)


@pytest.mark.asyncio
async def test_a_queued_input_runs_as_its_own_turn() -> None:
    """The input becomes turn two, after turn one is over, and never before."""
    model = QueueingModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    model.submit = lambda text: engine.submit_queued(live_context(), text, input_id="queue-1")

    await run_turn(engine, "hi")

    # The input was queued during the first request, and the first request never
    # saw it.
    assert "".join(message.content for message in model.inputs[0]) == "hi"
    assert engine.state() == machine.STATE_IDLE
    view = engine.snapshot()
    assert view.turn_index == 1
    assert tuple(item.id for item in view.queued) == ("queue-1",)

    await run_turn(engine, QUEUED_TEXT, input_id="queue-1")

    view = engine.snapshot()
    assert view.turn_index == 2
    assert view.queued == ()
    assert [message.content for message in engine.messages()] == ["hi", "first", QUEUED_TEXT, "second"]


@pytest.mark.asyncio
async def test_an_idle_engine_refuses_a_queued_input() -> None:
    engine = new_engine(None, None, None)
    await engine.ready()

    with pytest.raises(machine.UnexpectedEventError):
        await engine.submit_queued(live_context(), QUEUED_TEXT, input_id="queue-1")

    assert engine.snapshot().queued == ()


@pytest.mark.asyncio
async def test_queueing_never_drains_the_running_turn() -> None:
    """Submitting must not run the turn's queued action or end its run."""
    model = QueueingModel([ModelResponse(content="only")])
    engine = new_engine(model, None, None)
    await engine.ready()
    model.submit = lambda text: engine.submit_queued(live_context(), text, input_id="queue-1")

    await run_turn(engine, "hi")

    assert model.inputs and len(model.inputs) == 1
    assert engine.state() == machine.STATE_IDLE
    assert [message.content for message in engine.messages()] == ["hi", "only"]


# --- what the notification stream reports ------------------------------------


class BlockingModel:
    """Holds the first request open until the test releases it."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def next(
        self,
        ctx: object,
        messages: list[machine.Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await self.release.wait()
        return ModelResponse(content="done")


async def drain(queue: asyncio.Queue[SessionNotification]) -> list[SessionNotification]:
    seen: list[SessionNotification] = []
    while True:
        item = queue.get_nowait()
        seen.append(item)
        if item is NOTIFICATIONS_CLOSED:
            return seen


@pytest.mark.asyncio
async def test_starting_the_next_turn_reports_the_input_as_accepted() -> None:
    model = QueueingModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)
    model.submit = lambda text: session.submit_queued(text, input_id="queue-1")
    first: asyncio.Queue[SessionNotification] = asyncio.Queue()

    await session.run_turn(live_context(), "hi", first, asyncio.Queue())

    # Nothing in the first turn's stream may claim the input was accepted: it was
    # only held.
    assert not any(isinstance(item, QueuedInputAccepted) for item in await drain(first))

    second: asyncio.Queue[SessionNotification] = asyncio.Queue()
    await session.run_turn(live_context(), QUEUED_TEXT, second, asyncio.Queue(), input_id="queue-1")

    accepted = [item for item in await drain(second) if isinstance(item, QueuedInputAccepted)]
    assert accepted == [QueuedInputAccepted(input_id="queue-1", turn=2)]


@pytest.mark.asyncio
async def test_a_cancelled_turn_reports_the_queued_input_as_withdrawn() -> None:
    model = BlockingModel()
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)
    queue: asyncio.Queue[SessionNotification] = asyncio.Queue()

    turn = asyncio.create_task(session.run_turn(live_context(), "hi", queue, asyncio.Queue()))
    await asyncio.wait_for(model.started.wait(), timeout=5)
    await session.submit_queued(QUEUED_TEXT, input_id="queue-1")
    await session.cancel()
    model.release.set()
    with contextlib.suppress(BaseException):
        await asyncio.wait_for(turn, timeout=5)

    seen = await drain(queue)

    assert [item for item in seen if isinstance(item, QueuedInputWithdrawn)] == [
        QueuedInputWithdrawn(input_id="queue-1")
    ]
    assert not any(isinstance(item, QueuedInputAccepted) for item in seen)
    assert engine.snapshot().queued == ()
