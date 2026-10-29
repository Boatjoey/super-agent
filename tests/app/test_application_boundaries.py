"""Application compensation works with ports without concrete infrastructure."""

import asyncio

import pytest

from super_agent.application.delegation import Delegation, maxSubagentDepth, subagentDepthKey
from super_agent.application.mcp import MCPController
from super_agent.application.values import AgentProfile
from super_agent.errors import Cancelled, JoinedError
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.protocol.types import ModelResponse, ToolCall
from tests.fakes.application import DelegationEnvironment, MCPBackend
from tests.fakes.model import ScriptedModel, StreamingCancelModel


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_install", [False, True])
async def test_failed_mcp_add_restores_connection_catalog_and_configuration(fail_install: bool) -> None:
    backend = MCPBackend(fail_install=fail_install, fail_save=not fail_install)
    controller = MCPController(backend, {})

    with pytest.raises((OSError, ValueError)):
        await controller.add(live_context(), "server", "command", [])

    assert not backend.connected
    assert not backend.installed
    assert not backend.saved
    assert controller.list() == []
    assert not controller.configs
    assert backend.events == (
        ["connect", "install", "disconnect"]
        if fail_install
        else ["connect", "install", "save", "uninstall", "disconnect"]
    )


@pytest.mark.asyncio
async def test_failed_mcp_remove_reconnects_the_original_server() -> None:
    backend = MCPBackend()
    controller = MCPController(backend, {})
    await controller.add(live_context(), "server", "command", [])
    original = dict(controller.configs)
    backend.fail_save = True
    backend.events.clear()

    with pytest.raises(JoinedError, match="settings unavailable"):
        await controller.remove("server")

    assert backend.connected == {"server"}
    assert backend.installed == {"server"}
    assert backend.saved == original
    assert controller.configs == original
    assert backend.events == ["disconnect", "uninstall", "save", "connect", "install"]


@pytest.mark.asyncio
async def test_delegation_denies_child_approval_and_closes_the_child() -> None:
    environment = DelegationEnvironment(
        ScriptedModel(
            [ModelResponse(tool_calls=(ToolCall(id="call", name="unsafe", input="{}"),)), ModelResponse(content="done")]
        )
    )
    delegation = Delegation({"build": AgentProfile(name="build")}, "/parent", environment)

    result = await delegation.run(live_context(), ToolCall(input='{"prompt":"inspect","worktree":true}'))

    assert "Workspace: /child-worktree" in result
    assert result.endswith("done")
    assert environment.tools.calls == []
    assert any(message.role == "tool" for message in environment.children[0].snapshot().messages)
    assert environment.closed == 1
    assert environment.calls == ["model", "worktree", "child"]


@pytest.mark.asyncio
async def test_delegation_depth_limit_prevents_external_operations() -> None:
    environment = DelegationEnvironment(ScriptedModel([]))
    delegation = Delegation({"build": AgentProfile(name="build")}, "/parent", environment)
    ctx = live_context().with_value(subagentDepthKey, maxSubagentDepth)

    with pytest.raises(ValueError, match="maximum subagent depth"):
        await delegation.run(ctx, ToolCall(input='{"prompt":"inspect"}'))

    assert environment.calls == []


@pytest.mark.asyncio
async def test_cancelled_delegation_closes_child_and_settles_approval_listener() -> None:
    model = StreamingCancelModel()
    environment = DelegationEnvironment(model)
    delegation = Delegation({"build": AgentProfile(name="build")}, "/parent", environment)
    ctx = RunContext()
    task = asyncio.create_task(delegation.run(ctx, ToolCall(input='{"prompt":"inspect"}')))
    await asyncio.wait_for(model.started.wait(), timeout=2)
    ctx.cancel()

    with pytest.raises(Cancelled):
        await asyncio.wait_for(task, timeout=2)

    assert environment.closed == 1
