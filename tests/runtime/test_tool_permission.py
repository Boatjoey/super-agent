"""Permission checks execute the chosen call and preserve policy/approval semantics."""

from __future__ import annotations

import asyncio

import pytest

from super_agent.runtime import machine
from super_agent.runtime.engine import new_engine_with_executor_and_policy
from super_agent.runtime.execution import (
    PERMISSION_MODE_ASK,
    PERMISSION_MODE_BYPASS,
    PERMISSION_MODE_PLAN,
    DefaultScheduledActionExecutor,
    DefaultScheduledActionRunner,
    MemoryApprovalStore,
    PermissionChecked,
    PermissionMode,
    PermissionRules,
    QueuedAction,
    ScheduledActionInput,
    ToolDecision,
    new_approval_key,
    new_policy,
)
from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ToolSpec
from tests.fakes.execution import FakeToolRunner, PermissionGateExecutor
from tests.fakes.model import ScriptedModel

CALL = machine.ToolCall(id="call-2", name="write_file", input='{"path":"output.txt","content":"ok"}')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (PERMISSION_MODE_ASK, ToolDecision.DECISION_NEEDS_APPROVAL),
        (PERMISSION_MODE_PLAN, ToolDecision.DECISION_DENIED),
        (PERMISSION_MODE_BYPASS, ToolDecision.DECISION_RUN_DIRECTLY),
    ],
)
async def test_executor_checks_the_explicit_call(mode: PermissionMode, expected: ToolDecision) -> None:
    runner = DefaultScheduledActionRunner(
        DefaultScheduledActionExecutor(None, None), new_policy(mode, PermissionRules()), MemoryApprovalStore()
    )
    completion = await runner.run(
        live_context(),
        QueuedAction(action=machine.CheckToolPermission(call=CALL)),
        ScheduledActionInput(tool_specs=(ToolSpec(name="write_file", risky=True),)),
        lambda _: None,
    )
    result = completion.result
    assert isinstance(result, PermissionChecked)
    assert result.call == CALL
    assert result.decision == expected
    if expected != ToolDecision.DECISION_RUN_DIRECTLY:
        assert result.request.reason


@pytest.mark.asyncio
async def test_runner_policy_update_applies_to_next_check_and_preserves_always_allow() -> None:
    approvals = MemoryApprovalStore()
    runner = DefaultScheduledActionRunner(
        DefaultScheduledActionExecutor(None, None), new_policy(PERMISSION_MODE_PLAN, PermissionRules()), approvals
    )

    async def check() -> PermissionChecked:
        completion = await runner.run(
            live_context(),
            QueuedAction(action=machine.CheckToolPermission(call=CALL)),
            ScheduledActionInput(),
            lambda _: None,
        )
        assert isinstance(completion.result, PermissionChecked)
        return completion.result

    assert (await check()).decision == ToolDecision.DECISION_DENIED
    runner.set_policy(new_policy(PERMISSION_MODE_BYPASS, PermissionRules()))
    assert (await check()).decision == ToolDecision.DECISION_RUN_DIRECTLY
    runner.set_policy(new_policy(PERMISSION_MODE_PLAN, PermissionRules()))
    approvals.allow_always(new_approval_key(CALL))
    assert (await check()).decision == ToolDecision.DECISION_RUN_DIRECTLY


@pytest.mark.asyncio
async def test_permission_check_requires_policy_and_approval_store() -> None:
    with pytest.raises(ValueError, match="permission policy and approval store"):
        await DefaultScheduledActionExecutor(None, None).execute(
            live_context(), machine.CheckToolPermission(call=CALL), ScheduledActionInput(), lambda _: None
        )


@pytest.mark.asyncio
async def test_cancelled_permission_result_cannot_run_tool_or_change_next_turn() -> None:
    model = ScriptedModel([machine.ModelResponse(tool_calls=(CALL,)), machine.ModelResponse(content="fresh")])
    tools = FakeToolRunner(specs=(ToolSpec(name="write_file", risky=True),))
    executor = PermissionGateExecutor(model, tools)
    engine = new_engine_with_executor_and_policy(executor, new_policy(PERMISSION_MODE_BYPASS, PermissionRules()), None)
    await engine.ready()
    stale_turn = asyncio.create_task(
        engine.run_turn(live_context(), machine.UserMessageSubmitted(content="first"), None, None)
    )
    await asyncio.wait_for(executor.started.wait(), timeout=2)
    assert engine.state() == machine.STATE_ADVANCING_QUEUE
    assert executor.actions == [machine.CallModel(), machine.CheckToolPermission(call=CALL)]

    await engine.cancel()
    await engine.run_turn(live_context(), machine.UserMessageSubmitted(content="second"), None, None)
    executor.release.set()
    await stale_turn

    assert tools.calls == []
    assert executor.actions == [machine.CallModel(), machine.CheckToolPermission(call=CALL), machine.CallModel()]
    assert [
        (message.tool_call_id, message.content) for message in engine.messages() if message.role == machine.ROLE_TOOL
    ] == [(CALL.id, "not executed: cancelled")]
    assert engine.messages()[-1].content == "fresh"
    assert engine.state() == machine.STATE_IDLE
