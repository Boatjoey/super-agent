"""The step lifecycle the runtime spec requires.

A step is one logical model call plus the whole tool batch that call produced.
These cases walk the boundaries the spec names: a turn opens step one, a tool
batch ends one step and opens the next, a final answer closes the last step, and
every terminal path closes whatever step was open. The guards on the three
changes are covered too, because "explicit lifecycle" only holds if the applier
refuses to open or advance out of order.
"""

from __future__ import annotations

import pytest

from super_agent.runtime import machine


def sample_call() -> machine.ToolCall:
    return machine.ToolCall(id="call-1", name="bash", input="pwd")


def applier() -> machine.DefaultRuntimeDataChangeApplier:
    return machine.DefaultRuntimeDataChangeApplier()


def apply(data: machine.RuntimeData, event: machine.Event) -> machine.RuntimeData:
    """Commit one event the way the engine does: decide, apply, validate."""
    decision = machine.transition(machine.snapshot_from(data), event)
    return applier().apply_runtime_data_changes(data, decision).runtime_data


def idle_turn_started() -> machine.RuntimeData:
    return apply(
        machine.RuntimeData(state=machine.STATE_IDLE),
        machine.UserMessageSubmitted(content="hi"),
    )


def test_a_turn_opens_the_first_step() -> None:
    data = idle_turn_started()

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=1)


def test_a_final_answer_closes_the_last_step() -> None:
    data = idle_turn_started()

    data = apply(data, machine.AssistantMessageReceived(response=machine.ModelResponse(content="done")))

    assert data.state == machine.STATE_IDLE
    assert data.step is None


def test_a_tool_batch_ends_one_step_and_opens_the_next() -> None:
    call = sample_call()
    data = apply(idle_turn_started(), machine.ToolBatchReceived(calls=(call,)))

    # The batch belongs to the step that requested it, so the step is unchanged
    # while the calls are approved and executed.
    data = apply(data, machine.ToolCallReadyToRun(call=call))
    data = apply(data, machine.ToolResultReceived(call=call, result="ok"))
    assert data.step == machine.Step(index=1)

    data = apply(data, machine.ToolBatchFinished())

    assert data.state == machine.STATE_WAITING_LLM
    assert data.step == machine.Step(index=2)


def test_two_tool_round_trips_number_the_steps_in_order() -> None:
    call = sample_call()
    data = apply(idle_turn_started(), machine.ToolBatchReceived(calls=(call,)))
    data = apply(data, machine.ToolCallReadyToRun(call=call))
    data = apply(data, machine.ToolResultReceived(call=call, result="ok"))
    data = apply(data, machine.ToolBatchFinished())

    data = apply(data, machine.ToolBatchReceived(calls=(call,)))
    assert data.step == machine.Step(index=2)
    data = apply(data, machine.ToolCallReadyToRun(call=call))
    data = apply(data, machine.ToolResultReceived(call=call, result="ok"))
    data = apply(data, machine.ToolBatchFinished())

    assert data.step == machine.Step(index=3)


@pytest.mark.parametrize(
    "event",
    [
        machine.CancelRequested(),
        machine.ErrorOccurred(err=RuntimeError("boom")),
        machine.ResetRequested(),
    ],
    ids=["cancel", "error", "reset"],
)
def test_every_terminal_path_closes_the_open_step(event: machine.Event) -> None:
    data = idle_turn_started()

    data = apply(data, event)

    assert data.state == machine.STATE_IDLE
    assert data.step is None


def test_cancelling_while_a_tool_runs_still_closes_the_step() -> None:
    call = sample_call()
    data = apply(idle_turn_started(), machine.ToolBatchReceived(calls=(call,)))
    data = apply(data, machine.ToolCallReadyToRun(call=call))

    data = apply(data, machine.CancelRequested())

    assert data.step is None
    assert [message.content for message in data.messages if message.role == machine.ROLE_TOOL] == ["cancelled"]


def test_cancelling_an_idle_engine_needs_no_step_to_close() -> None:
    """The terminal events are global, so they must tolerate having nothing open."""
    decision = machine.transition(
        machine.snapshot_from(machine.RuntimeData(state=machine.STATE_IDLE)),
        machine.CancelRequested(),
    )

    committed = applier().apply_runtime_data_changes(machine.RuntimeData(state=machine.STATE_IDLE), decision)

    assert committed.runtime_data.step is None


def test_opening_a_step_while_one_is_open_is_refused() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        applier().apply_runtime_data_changes(
            machine.RuntimeData(state=machine.STATE_WAITING_LLM, step=machine.Step(index=1)),
            machine.TransitionResult(
                next_state=machine.STATE_WAITING_LLM,
                runtime_data_changes=(machine.OpenStep(),),
            ),
        )
    assert raised.value.reason == "cannot open a step while one is open"


def test_advancing_without_an_open_step_is_refused() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        applier().apply_runtime_data_changes(
            machine.RuntimeData(state=machine.STATE_IDLE),
            machine.TransitionResult(
                next_state=machine.STATE_IDLE,
                runtime_data_changes=(machine.AdvanceStep(),),
            ),
        )
    assert raised.value.reason == "cannot advance without an open step"


def test_a_running_state_without_a_step_is_invalid() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        machine.snapshot_from(machine.RuntimeData(state=machine.STATE_WAITING_LLM))
    assert raised.value.reason == "WaitingLLM has no open step"


def test_an_idle_state_holding_a_step_is_invalid() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        machine.snapshot_from(machine.RuntimeData(state=machine.STATE_IDLE, step=machine.Step(index=1)))
    assert raised.value.reason == "Idle contains an open step"


def test_a_step_number_below_one_is_invalid() -> None:
    with pytest.raises(machine.InvariantViolationError) as raised:
        machine.snapshot_from(machine.RuntimeData(state=machine.STATE_WAITING_LLM, step=machine.Step(index=0)))
    assert raised.value.reason == "step index must be at least one"


def test_reset_from_a_running_state_drops_the_step() -> None:
    """Reset already clears every other piece of run context; the step goes too."""
    data = apply(idle_turn_started(), machine.ResetRequested())

    assert data.step is None
