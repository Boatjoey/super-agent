"""Conversation replacement validates a candidate before changing committed state."""

from __future__ import annotations

from copy import deepcopy

import pytest

from super_agent.runtime import machine
from super_agent.runtime.engine import commands as engine_commands, new_engine
from super_agent.runtime.protocol.run_context import live_context
from tests.fakes.execution import FakeToolRunner
from tests.fakes.model import ScriptedModel

RUNNING_STATES = (
    machine.STATE_WAITING_LLM,
    machine.STATE_ADVANCING_QUEUE,
    machine.STATE_WAITING_APPROVAL,
    machine.STATE_RUNNING_TOOL,
)
CALL = machine.ToolCall(id="call-1", name="bash", input='{"command":"pwd"}')


def execution_context(state: machine.State) -> machine.RuntimeData:
    data = machine.RuntimeData(
        state=state,
        messages=[machine.Message(role=machine.ROLE_USER, content="original")],
        step=machine.Step(index=3),
        steering=(machine.SteeringInput(content="steer"),),
        queued=(machine.QueuedInput(id="follow-up", content="next turn"),),
        turn=7,
    )
    if state == machine.STATE_WAITING_LLM:
        data.streaming_content = "partial"
        data.streaming_reasoning = "thinking"
    else:
        data.tool_batch = machine.ToolCallBatch(id="batch", calls=[CALL])
        if state == machine.STATE_WAITING_APPROVAL:
            data.tool_batch.index = 1
            data.pending_tool = CALL
            data.pending_permission = machine.PermissionRequest(tool_name=CALL.name)
        elif state == machine.STATE_RUNNING_TOOL:
            data.tool_batch.index = 1
            data.current_tool = CALL
    machine.validate_runtime_data(data)
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("state", RUNNING_STATES)
async def test_replacement_validation_failure_preserves_committed_state_and_actions(
    state: machine.State, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = new_engine(None, None, None)
    original = execution_context(state)
    before = deepcopy(original)
    engine._runtime_data = original  # pyright: ignore[reportPrivateUsage]
    run_id, context = engine._runs.start_run(live_context())  # pyright: ignore[reportPrivateUsage]
    queued = engine._action_queue.queue(run_id, machine.CallModel())  # pyright: ignore[reportPrivateUsage]
    replacement = [machine.Message(role=machine.ROLE_SYSTEM, content="replacement")]
    candidates: list[machine.RuntimeData] = []
    failure = machine.InvariantViolationError("injected replacement validation failure")

    def reject_candidate(candidate: machine.RuntimeData) -> None:
        candidates.append(candidate)
        raise failure

    monkeypatch.setattr(engine_commands, "validate_runtime_data", reject_candidate)
    with pytest.raises(machine.InvariantViolationError) as raised:
        await engine.replace_messages(replacement)

    assert raised.value is failure
    assert engine._runtime_data is original  # pyright: ignore[reportPrivateUsage]
    assert original == before
    assert engine.messages() == before.messages
    assert engine._action_queue.len() == 1  # pyright: ignore[reportPrivateUsage]
    assert engine._action_queue.pop() == queued  # pyright: ignore[reportPrivateUsage]
    assert len(candidates) == 1
    assert candidates[0] is not original
    assert candidates[0].state == machine.STATE_IDLE
    assert candidates[0].messages == replacement
    assert context.done().is_set()
    assert not engine._runs.is_current(run_id)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", RUNNING_STATES)
async def test_replacement_commits_new_state_without_mutating_previous_state(state: machine.State) -> None:
    engine = new_engine(ScriptedModel([machine.ModelResponse(content="fresh reply")]), FakeToolRunner(), None)
    original = execution_context(state)
    before = deepcopy(original)
    engine._runtime_data = original  # pyright: ignore[reportPrivateUsage]
    run_id, context = engine._runs.start_run(live_context())  # pyright: ignore[reportPrivateUsage]
    engine._action_queue.queue(run_id, machine.CallModel())  # pyright: ignore[reportPrivateUsage]
    replacement = [machine.Message(role=machine.ROLE_SYSTEM, content="replacement")]

    await engine.replace_messages(replacement)

    assert engine._runtime_data is not original  # pyright: ignore[reportPrivateUsage]
    assert original == before
    assert engine._runtime_data == machine.RuntimeData(  # pyright: ignore[reportPrivateUsage]
        state=machine.STATE_IDLE, messages=replacement, queued=before.queued, turn=before.turn
    )
    assert engine._action_queue.len() == 0  # pyright: ignore[reportPrivateUsage]
    assert context.done().is_set()
    assert not engine._runs.is_current(run_id)  # pyright: ignore[reportPrivateUsage]
    replacement.append(machine.Message(role=machine.ROLE_USER, content="caller mutation"))
    assert [message.content for message in engine.messages()] == ["replacement"]

    await engine.run_turn(live_context(), machine.UserMessageSubmitted(content="continue"), None, None)
    assert [message.content for message in engine.messages()] == ["replacement", "continue", "fresh reply"]
    assert engine.state() == machine.STATE_IDLE
