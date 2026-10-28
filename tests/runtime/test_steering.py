"""Steering: an input submitted while the turn is already running.

The runtime spec gives such an input to the *current* turn, and accepts it at the
next step boundary rather than when it arrives. That delay is the whole point: a
request may already be in flight, and a tool may be running, so nothing may be
rewritten or interrupted. These cases walk the acceptance point from both sides —
the machine alone, and a real engine loop — because the interesting failures
(state that never continues, input applied twice, input surviving its turn) only
show up when the two are wired together.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

import pytest

from super_agent.runtime import machine
from super_agent.runtime.engine import Engine, new_engine
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.protocol.types import ModelResponse, StreamChunk, ToolCall, ToolSpec
from super_agent.runtime.session import (
    NOTIFICATIONS_CLOSED,
    SessionNotification,
    SteeringAccepted,
    SteeringWithdrawn,
    new_session,
)

STEERING_TEXT = "also check the tests"


def applier() -> machine.DefaultRuntimeDataChangeApplier:
    return machine.DefaultRuntimeDataChangeApplier()


def apply(data: machine.RuntimeData, event: machine.Event) -> machine.RuntimeData:
    """Commit one event the way the engine does: decide, apply, validate."""
    decision = machine.transition(machine.snapshot_from(data), event)
    return applier().apply_runtime_data_changes(data, decision).runtime_data


def sample_call() -> machine.ToolCall:
    return machine.ToolCall(id="call-1", name="bash", input="pwd")


def running_turn() -> machine.RuntimeData:
    """A turn in ``WaitingLLM`` with step one open."""
    return apply(machine.RuntimeData(state=machine.STATE_IDLE), machine.UserMessageSubmitted(content="hi"))


def steering_pending() -> machine.RuntimeData:
    return apply(running_turn(), machine.SteeringSubmitted(content=STEERING_TEXT))


def contents(data: machine.RuntimeData) -> list[str]:
    return [message.content for message in data.messages]


# --- where the input waits ---------------------------------------------------


def test_steering_is_held_instead_of_being_applied_immediately() -> None:
    """Nothing joins the conversation while a request may still be in flight."""
    data = steering_pending()

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=1)
    assert contents(data) == ["hi"]
    assert data.steering == (machine.SteeringInput(content=STEERING_TEXT),)


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
def test_every_running_state_accepts_steering_without_changing_state(state: machine.State) -> None:
    event = machine.SteeringSubmitted(content=STEERING_TEXT)
    result = machine.transition(_snapshot_in(state), event)

    assert result.next_state == state
    assert result.runtime_data_changes == (machine.QueueSteering(input=machine.SteeringInput(content=STEERING_TEXT)),)
    assert result.action_plan.schedule == ()


@pytest.mark.parametrize("state", [machine.STATE_IDLE, machine.STATE_INITIALIZING], ids=["idle", "initializing"])
def test_steering_cannot_start_a_turn(state: machine.State) -> None:
    """Steering belongs to a turn in flight; starting one stays the other event's job."""
    with pytest.raises(machine.UnexpectedEventError):
        machine.transition(_snapshot_in(state), machine.SteeringSubmitted(content=STEERING_TEXT))


def _snapshot_in(state: machine.State) -> machine.MachineSnapshot:
    call = sample_call()
    data = machine.RuntimeData(state=state)
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
    return machine.snapshot_from(data)


# --- when it is accepted -----------------------------------------------------


def test_a_tool_batch_accepts_the_waiting_input_before_the_next_request() -> None:
    call = sample_call()
    data = steering_pending()

    data = apply(data, machine.ToolBatchReceived(calls=(call,)))
    data = apply(data, machine.ToolCallReadyToRun(call=call))
    data = apply(data, machine.ToolResultReceived(call=call, result="ok"))

    # The batch belongs to step one, so the input stays out of the conversation
    # until the batch is settled.
    assert data.step == machine.Step(index=1)
    assert STEERING_TEXT not in contents(data)

    data = apply(data, machine.ToolBatchFinished())

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=2)
    assert data.messages[-1].role == machine.ROLE_USER
    assert data.messages[-1].content == STEERING_TEXT
    assert data.steering == ()


def test_a_final_answer_with_a_waiting_input_continues_the_turn() -> None:
    data = steering_pending()

    data = apply(data, machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=2)
    assert contents(data) == ["hi", "done", STEERING_TEXT]


def test_a_final_answer_without_a_waiting_input_still_ends_the_turn() -> None:
    """The acceptance request at the boundary is a no-op when nothing waits."""
    data = apply(running_turn(), machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    assert data.state == machine.STATE_IDLE
    assert data.step is None
    assert contents(data) == ["hi", "done"]


def test_several_inputs_are_accepted_in_one_step_in_submission_order() -> None:
    data = apply(steering_pending(), machine.SteeringSubmitted(content="and the docs"))

    data = apply(data, machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    assert contents(data) == ["hi", "done", STEERING_TEXT, "and the docs"]
    assert data.step == machine.Step(index=2)


def test_an_accepted_input_is_never_accepted_twice() -> None:
    data = apply(steering_pending(), machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    data = apply(data, machine.AssistantMessageReceived(response=machine.ModelResponse(content="again")))

    assert contents(data) == ["hi", "done", STEERING_TEXT, "again"]
    assert data.step is None
    assert data.steering == ()


# --- when a turn ends, its waiting input ends with it ------------------------


@pytest.mark.parametrize(
    "event",
    [
        machine.CancelRequested(),
        machine.ErrorOccurred(err=RuntimeError("boom")),
        machine.ResetRequested(),
    ],
    ids=["cancel", "error", "reset"],
)
def test_a_turn_that_ends_discards_the_waiting_input(event: machine.Event) -> None:
    """An input that never reached a request must not outlive its turn."""
    data = steering_pending()

    data = apply(data, event)

    assert data.state == machine.STATE_IDLE
    assert data.steering == ()
    assert STEERING_TEXT not in contents(data)


def test_an_idle_engine_cannot_hold_a_waiting_input() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        machine.snapshot_from(
            machine.RuntimeData(state=machine.STATE_IDLE, steering=(machine.SteeringInput(content=STEERING_TEXT),))
        )
    assert raised.value.reason == "Idle holds unconsumed steering"


# --- the same behaviour through a real engine loop ---------------------------


class SteeringModel:
    """Replays responses and submits one input during a chosen model call.

    It submits from inside ``next``, which is exactly the "answer is streaming"
    window: the request is in flight and the terminal has already accepted the
    user's text.
    """

    def __init__(
        self,
        responses: Sequence[ModelResponse],
        *,
        submit_on_call: int = 0,
        submit: Callable[[str], object] | None = None,
    ) -> None:
        self.responses: list[ModelResponse] = list(responses)
        self.submit_on_call = submit_on_call
        self.submit = submit
        self.inputs: list[tuple[machine.Message, ...]] = []

    async def next(
        self,
        ctx: RunContext,
        messages: list[machine.Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        self.inputs.append(tuple(messages))
        index = len(self.inputs) - 1
        if index == self.submit_on_call and self.submit is not None:
            result = self.submit(STEERING_TEXT)
            assert asyncio.iscoroutine(result)
            await result
        return self.responses[index]


class SteeringToolRunner:
    """A tool that submits steering while it runs, then answers."""

    def __init__(self) -> None:
        self.engine: Engine | None = None
        self.calls: list[str] = []

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(name="bash")]

    async def run(self, ctx: RunContext, call: ToolCall) -> str:
        assert self.engine is not None
        self.calls.append(call.name)
        await self.engine.submit_steering(live_context(), STEERING_TEXT)
        return "ok"


async def run_turn(engine: Engine, content: str) -> None:
    await engine.run_turn(live_context(), machine.UserMessageSubmitted(content=content), None, None)


@pytest.mark.asyncio
async def test_an_input_during_a_tool_run_reaches_the_next_request() -> None:
    model = SteeringModel(
        [
            ModelResponse(tool_calls=(ToolCall(id="call-1", name="bash", input="printf ok"),)),
            ModelResponse(content="done"),
        ]
    )
    tools = SteeringToolRunner()
    engine = new_engine(model, tools, None)
    tools.engine = engine
    await engine.ready()

    await run_turn(engine, "use bash")

    assert engine.state() == machine.STATE_IDLE
    assert tools.calls == ["bash"]
    second_request = model.inputs[1]
    assert second_request[-2].role == machine.ROLE_TOOL
    assert second_request[-1].role == machine.ROLE_USER
    assert second_request[-1].content == STEERING_TEXT
    assert [message.content for message in engine.messages()] == ["use bash", "", "ok", STEERING_TEXT, "done"]


@pytest.mark.asyncio
async def test_an_input_during_the_final_answer_keeps_the_turn_running() -> None:
    """A submitted input is not lost to the answer that happened to be arriving."""
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()

    async def submit(text: str) -> None:
        await engine.submit_steering(live_context(), text)

    model.submit = submit

    await run_turn(engine, "hi")

    assert engine.state() == machine.STATE_IDLE
    assert len(model.inputs) == 2
    assert model.inputs[1][-1].content == STEERING_TEXT
    assert [message.content for message in engine.messages()] == ["hi", "first", STEERING_TEXT, "second"]


@pytest.mark.asyncio
async def test_the_session_boundary_accepts_steering_the_same_way() -> None:
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)

    async def submit(text: str) -> None:
        await session.submit_steering(text)

    model.submit = submit

    await run_turn(engine, "hi")

    assert [message.content for message in engine.messages()] == ["hi", "first", STEERING_TEXT, "second"]


@pytest.mark.asyncio
async def test_an_idle_engine_refuses_steering() -> None:
    engine = new_engine(None, None, None)
    await engine.ready()

    with pytest.raises(machine.UnexpectedEventError):
        await engine.submit_steering(live_context(), STEERING_TEXT)

    assert engine.messages() == []


@pytest.mark.asyncio
async def test_steering_never_drains_the_running_turn() -> None:
    """Submitting must not run the turn's queued action or end its run.

    The engine's ordinary dispatch path drains the queue after committing, which
    would break here: the queue belongs to the turn running in another task. This
    case fails loudly if the steering path is ever rerouted through it.
    """
    model = SteeringModel(
        [
            ModelResponse(tool_calls=(ToolCall(id="call-1", name="bash", input="printf ok"),)),
            ModelResponse(content="done"),
        ]
    )
    tools = SteeringToolRunner()
    engine = new_engine(model, tools, None)
    tools.engine = engine
    await engine.ready()

    await run_turn(engine, "use bash")

    assert engine.state() == machine.STATE_IDLE
    assert len(model.inputs) == 2
    assert tools.calls == ["bash"]


# --- the caller's correlation id and the receipts it enables ------------------


def test_the_held_input_keeps_the_callers_id() -> None:
    """The id is carried, not interpreted: it is how the receipt names the input."""
    data = apply(running_turn(), machine.SteeringSubmitted(content=STEERING_TEXT, input_id="steer-7"))

    assert data.steering == (machine.SteeringInput(id="steer-7", content=STEERING_TEXT),)


@pytest.mark.asyncio
async def test_the_view_reports_the_step_an_input_would_join() -> None:
    """A submission needs the step it lands in and what is already waiting there."""
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()

    seen: list[tuple[int, tuple[str, ...]]] = []

    async def submit(text: str) -> None:
        await engine.submit_steering(live_context(), text, input_id="steer-1")
        view = engine.snapshot()
        seen.append((view.step_index, tuple(item.id for item in view.steering)))

    model.submit = submit

    await run_turn(engine, "hi")

    assert seen == [(1, ("steer-1",))]


async def drain[T](queue: asyncio.Queue[T]) -> list[T]:
    """Everything a turn published, in order, up to the close marker."""
    seen: list[T] = []
    while True:
        item = queue.get_nowait()
        seen.append(item)
        if item is NOTIFICATIONS_CLOSED:
            return seen


@pytest.mark.asyncio
async def test_the_session_reports_the_step_that_took_the_input_up() -> None:
    """Acceptance is a later, named event — not the submission returning."""
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)
    notifications: asyncio.Queue[SessionNotification] = asyncio.Queue()

    async def submit(text: str) -> None:
        await session.submit_steering(text, input_id="steer-1")

    model.submit = submit

    await session.run_turn(live_context(), "hi", notifications, asyncio.Queue())

    accepted = [item for item in await drain(notifications) if isinstance(item, SteeringAccepted)]
    assert accepted == [SteeringAccepted(input_id="steer-1", step=2)]


@pytest.mark.asyncio
async def test_a_held_input_the_turn_never_reaches_is_withdrawn() -> None:
    """A failed turn takes the waiting input with it, and says so."""
    model = FailingAfterSteeringModel()
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)
    notifications: asyncio.Queue[SessionNotification] = asyncio.Queue()
    model.submit = lambda text: session.submit_steering(text, input_id="steer-9")

    with pytest.raises(RuntimeError):
        await session.run_turn(live_context(), "hi", notifications, asyncio.Queue())

    published = await drain(notifications)
    assert [item for item in published if isinstance(item, SteeringWithdrawn)] == [
        SteeringWithdrawn(input_id="steer-9")
    ]
    assert not [item for item in published if isinstance(item, SteeringAccepted)]


@pytest.mark.asyncio
async def test_an_input_without_an_id_is_not_announced() -> None:
    """An unnamed input cannot be reported against, so the runtime stays silent."""
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    session = new_session(engine)
    notifications: asyncio.Queue[SessionNotification] = asyncio.Queue()

    async def submit(text: str) -> None:
        await session.submit_steering(text)

    model.submit = submit

    await session.run_turn(live_context(), "hi", notifications, asyncio.Queue())

    published = await drain(notifications)
    assert not [item for item in published if isinstance(item, (SteeringAccepted, SteeringWithdrawn))]
    assert [message.content for message in engine.messages()] == ["hi", "first", STEERING_TEXT, "second"]


class FailingAfterSteeringModel:
    """Holds an input, then fails the turn before the next step begins."""

    def __init__(self) -> None:
        self.submit: Callable[[str], object] | None = None

    async def next(
        self,
        ctx: RunContext,
        messages: list[machine.Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        assert self.submit is not None
        result = self.submit(STEERING_TEXT)
        assert asyncio.iscoroutine(result)
        await result
        raise RuntimeError("model failed after the input arrived")
