"""The web route table, exercised without a socket.

Routing is a pure function of a request, so the interesting behaviour — which
status each intent gets, and which events a turn publishes — is testable here
rather than through a browser.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from super_agent import frontend
from super_agent.web import EventHub, Request, Router, TurnRunner
from tests.fakes.frontend import AwaitingConversation, FakeConversation


def build(conversation: FakeConversation) -> tuple[Router, EventHub, TurnRunner]:
    hub = EventHub()
    runner = TurnRunner(conversation, hub)
    return Router(conversation, runner, hub), hub, runner


async def call(router: Router, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    request = Request(method=method, path=path, body=json.dumps(body).encode("utf-8") if body is not None else b"")
    response = await router.handle(request)
    payload: Any = json.loads(response.body.decode("utf-8")) if response.body else None
    return response.status, payload


async def take(subscription: Any, count: int) -> list[dict[str, Any]]:
    """Read ``count`` events, failing the test rather than hanging forever."""
    events: list[dict[str, Any]] = []
    for _ in range(count):
        events.append(await subscription.get())
    return events


@pytest.mark.asyncio
async def test_snapshot_answers_with_the_view_and_the_configuration() -> None:
    conversation = FakeConversation(
        view=frontend.ConversationView(
            agent_status=frontend.AgentStatus(label="Idle"),
            messages=(frontend.Message(role=frontend.ROLE_USER, content="hi"),),
        ),
        agents=[frontend.AgentSummary(name="build", provider="deepseek", model="deepseek-chat", permission_mode="ask")],
        sessions=[frontend.SessionSummary(id="s1", title="one", model="deepseek-chat")],
    )
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/snapshot")

    assert status == 200
    assert payload["snapshot"]["messages"][0]["content"] == "hi"
    assert payload["config"]["model"] == "deepseek-chat"
    assert payload["config"]["permission_mode"] == "ask"
    # The configuration is the contract's value, not a mapping each transport
    # invents: identity and capabilities travel with it.
    assert payload["config"]["agent"] == "build"
    assert payload["config"]["capabilities"] == list(frontend.CAPABILITIES)
    assert "reasoning_effort" in payload["config"]
    assert payload["running"] is False


@pytest.mark.asyncio
async def test_a_turn_reports_start_notifications_and_a_final_snapshot() -> None:
    conversation = FakeConversation(
        notifications=[
            frontend.AgentStatusChanged(status=frontend.AgentStatus(label="WaitingLLM", busy=True)),
            frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="done")),
        ]
    )
    router, hub, runner = build(conversation)
    subscription = router.subscribe()

    status, payload = await call(router, "POST", "/api/turns", {"text": "hello"})
    await runner.wait()

    assert status == 202
    assert payload == {"accepted": True}
    assert conversation.queries == ["hello"]
    events = await take(subscription, 5)
    assert [event["kind"] for event in events] == [
        "Snapshot",  # the greeting, so a fresh tab never starts blank
        "TurnStarted",
        "AgentStatusChanged",
        "MessageAppended",
        "TurnFinished",
    ]
    assert hub.subscribers == 1


@pytest.mark.asyncio
async def test_a_second_turn_is_refused_while_one_runs() -> None:
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)

    await call(router, "POST", "/api/turns", {"text": "first"})
    await conversation.started.wait()
    status, payload = await call(router, "POST", "/api/turns", {"text": "second"})

    assert status == 409
    assert "already running" in payload["error"]
    await runner.cancel()
    await runner.wait()


@pytest.mark.asyncio
async def test_an_approval_reaches_the_blocked_turn() -> None:
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)
    subscription = router.subscribe()

    await call(router, "POST", "/api/turns", {"text": "run"})
    await conversation.started.wait()
    status, _payload = await call(router, "POST", "/api/approvals", {"decision": "deny", "request_id": "approval-1"})

    assert status == 200
    await runner.wait()
    assert conversation.decision == "deny"
    events = await take(subscription, 5)
    assert [event["kind"] for event in events] == [
        "Snapshot",
        "TurnStarted",
        "ToolApprovalRequested",
        "ToolApprovalCleared",
        "TurnFinished",
    ]
    assert events[-1]["error"] is None, "a turn that finished normally must not look like a failure"


@pytest.mark.asyncio
async def test_an_approval_with_nothing_pending_is_a_conflict() -> None:
    router, _hub, _runner = build(FakeConversation())

    status, payload = await call(router, "POST", "/api/approvals", {"decision": "once"})

    assert status == 409
    assert "waiting" in payload["error"]


@pytest.mark.asyncio
async def test_an_approval_that_names_another_request_is_refused() -> None:
    """A stale click must not approve a tool call the user never saw."""
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)
    await call(router, "POST", "/api/turns", {"text": "run"})
    await conversation.started.wait()

    status, payload = await call(
        router, "POST", "/api/approvals", {"decision": "once", "request_id": "approval-from-an-older-prompt"}
    )

    assert status == 409
    assert "no longer pending" in payload["error"]
    assert conversation.decision is None
    await runner.cancel()
    await runner.wait()


@pytest.mark.asyncio
async def test_a_second_answer_to_the_same_request_is_refused() -> None:
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)
    await call(router, "POST", "/api/turns", {"text": "run"})
    await conversation.started.wait()

    first = await call(router, "POST", "/api/approvals", {"decision": "deny", "request_id": "approval-1"})
    second = await call(router, "POST", "/api/approvals", {"decision": "once", "request_id": "approval-1"})

    assert first[0] == 200
    assert second[0] == 409
    await runner.wait()
    assert conversation.decision == "deny"


@pytest.mark.asyncio
async def test_a_snapshot_names_the_request_a_rebuilt_tab_must_answer() -> None:
    """A tab that reconnects mid-approval has no event history, only the view."""
    conversation = FakeConversation(
        view=frontend.ConversationView(
            agent_status=frontend.AgentStatus(label="WaitingApproval", awaiting_approval=True),
            pending_tool=frontend.ToolCall(id="call-1", name="run_command", input="{}"),
            pending_permission=frontend.PermissionRequest(tool_name="run_command"),
            pending_approval_id="approval-9",
        )
    )
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/snapshot")

    assert status == 200
    assert payload["snapshot"]["pending_approval_id"] == "approval-9"


@pytest.mark.asyncio
async def test_an_unknown_decision_is_refused_before_it_reaches_the_runtime() -> None:
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)
    await call(router, "POST", "/api/turns", {"text": "run"})
    await conversation.started.wait()

    status, payload = await call(router, "POST", "/api/approvals", {"decision": "yes-please"})

    assert status == 400
    assert "unknown approval decision" in payload["error"]
    await runner.cancel()
    await runner.wait()


@pytest.mark.asyncio
async def test_steering_returns_the_receipt_it_received() -> None:
    conversation = FakeConversation(receipts=[frontend.SteeringReceipt.rejected("steer-1", "no turn is running")])
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/steering", {"text": "also this"})

    assert status == 200
    assert payload == {"input_id": "steer-1", "status": "rejected", "reason": "no turn is running"}
    assert conversation.steers == ["also this"]


@pytest.mark.asyncio
async def test_queued_input_returns_the_receipt_it_received() -> None:
    """Queueing is a different owner from steering: the next turn, not this one."""
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/queue", {"text": "then this"})

    assert status == 200
    assert payload == {"input_id": "queue-1", "status": "queued", "reason": ""}
    assert conversation.queued == ["then this"]


@pytest.mark.asyncio
async def test_an_empty_prompt_never_becomes_a_turn() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/turns", {"text": "   "})

    assert status == 400
    assert payload["error"] == "text is required"
    assert conversation.queries == []


@pytest.mark.asyncio
async def test_cancel_is_accepted_and_forwarded() -> None:
    conversation = AwaitingConversation()
    router, _hub, runner = build(conversation)
    await call(router, "POST", "/api/turns", {"text": "run"})
    await conversation.started.wait()

    status, payload = await call(router, "POST", "/api/cancel")

    assert (status, payload) == (200, {"ok": True})
    assert conversation.cancellations == 1
    assert conversation.last_turn is not None
    assert conversation.last_turn[1].cancelled is True
    await runner.wait()


@pytest.mark.asyncio
async def test_saved_sessions_are_listed_resumed_renamed_and_deleted() -> None:
    conversation = FakeConversation(sessions=[frontend.SessionSummary(id="s1", title="one")])
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/sessions")
    assert status == 200
    assert payload["sessions"] == [
        {"id": "s1", "title": "one", "provider": "", "model": "", "cwd": "", "parent_id": ""}
    ]

    assert (await call(router, "POST", "/api/sessions/s1/resume"))[0] == 200
    assert (await call(router, "POST", "/api/sessions/s1/rename", {"title": "new"}))[0] == 200
    assert (await call(router, "DELETE", "/api/sessions/s1"))[0] == 200

    assert conversation.resumes == ["s1"]
    assert conversation.renames == [("s1", "new")]
    assert conversation.deletions == ["s1"]


@pytest.mark.asyncio
async def test_resuming_publishes_a_fresh_snapshot_for_every_tab() -> None:
    router, _hub, _runner = build(FakeConversation())
    subscription = router.subscribe()
    await take(subscription, 1)

    await call(router, "POST", "/api/sessions/s1/resume")

    event = await subscription.get()
    assert event["kind"] == "Snapshot"


@pytest.mark.asyncio
async def test_the_permission_mode_is_changed_through_the_port() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/permission-mode", {"mode": "accept-edits"})

    assert status == 200
    assert payload["permission_mode"] == "accept-edits"
    assert conversation.modes == ["accept-edits"]


@pytest.mark.asyncio
async def test_unknown_paths_and_methods_are_not_found() -> None:
    router, _hub, _runner = build(FakeConversation())

    assert (await call(router, "GET", "/api/nope"))[0] == 404
    assert (await call(router, "POST", "/api/snapshot"))[0] == 404
    assert (await call(router, "GET", "/index.html"))[0] == 404


@pytest.mark.asyncio
async def test_a_failed_turn_reports_a_failure_a_tab_can_show() -> None:
    conversation = FakeConversation(
        error=frontend.Failure(message="model refused", code=frontend.FAILED, operation="run_turn")
    )
    router, _hub, runner = build(conversation)
    subscription = router.subscribe()

    await call(router, "POST", "/api/turns", {"text": "hi"})
    await runner.wait()

    events = await take(subscription, 3)
    assert events[-1]["kind"] == "TurnFinished"
    assert events[-1]["error"]["message"] == "model refused"
    assert events[-1]["error"]["operation"] == "run_turn"


@pytest.mark.asyncio
async def test_the_memory_route_reports_the_state_and_the_lines() -> None:
    """The browser is told what it would actually get, not what it hopes for."""
    conversation = FakeConversation()
    conversation.memory_items = ["Prefer concise answers"]
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/memory")

    assert status == 200
    assert payload["enabled"] is True
    assert payload["backend"] == "store"
    assert payload["items"] == ["Prefer concise answers"]


@pytest.mark.asyncio
async def test_the_memory_switch_is_turned_through_the_route() -> None:
    """Turning the memory off is one call, and the answer says it took."""
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/memory", {"enabled": False})

    assert status == 200
    assert payload["enabled"] is False
    assert conversation.memory_switches == [False]


@pytest.mark.asyncio
async def test_the_memory_switch_refuses_a_value_that_is_not_a_switch() -> None:
    """A missing or misspelled switch is a client error, not a silent "on"."""
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "POST", "/api/memory", {}))[0] == 400
    assert (await call(router, "POST", "/api/memory", {"enabled": "maybe"}))[0] == 400
    assert conversation.memory_switches == []


@pytest.mark.asyncio
async def test_providers_are_listed_with_the_credential_redacted() -> None:
    """The list says which providers exist and whether each has a key, never the key."""
    conversation = FakeConversation()
    conversation.providers = [
        frontend.ProviderView(name="deepseek", model="deepseek-reasoner", has_key=False),
        frontend.ProviderView(name="openai", model="gpt-4o", has_key=True),
    ]
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/providers")

    assert status == 200
    assert [item["name"] for item in payload["providers"]] == ["deepseek", "openai"]
    assert payload["providers"][0]["has_key"] is False
    assert payload["providers"][1]["has_key"] is True


@pytest.mark.asyncio
async def test_configuring_a_provider_needs_a_key() -> None:
    """An empty key is a client error: configuring nothing is not configuring."""
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "POST", "/api/providers/deepseek", {"model": "m"}))[0] == 400
    assert conversation.configured == []


@pytest.mark.asyncio
async def test_configuring_a_provider_persists_and_reports() -> None:
    """Setting a key forwards to the application and answers with the new config."""
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/providers/deepseek", {"api_key": "sk-new", "model": "m2"})

    assert status == 200
    assert conversation.configured == [("deepseek", "sk-new", "m2")]
    assert payload["provider"] == conversation.config_view().provider


async def call_query(router: Router, method: str, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
    response = await router.handle(Request(method=method, path=path, query=query))
    payload: Any = json.loads(response.body.decode("utf-8")) if response.body else None
    return response.status, payload


@pytest.mark.asyncio
async def test_mcp_servers_are_listed_added_removed_and_restarted() -> None:
    conversation = FakeConversation()
    conversation.mcp_servers = [frontend.MCPServerSummary(name="fs", tools=("read_file",))]
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/mcp")
    assert (status, payload) == (200, {"servers": [{"name": "fs", "tools": ["read_file"]}]})

    status, _ = await call(router, "POST", "/api/mcp", {"name": "git", "command": "git-mcp", "args": ["--stdio"]})
    assert status == 200
    assert conversation.added_mcp == [("git", "git-mcp", ["--stdio"])]

    assert (await call(router, "DELETE", "/api/mcp/git"))[0] == 200
    assert conversation.removed_mcp == ["git"]

    assert (await call(router, "POST", "/api/mcp/git/restart"))[0] == 200
    assert conversation.restarted_mcp == ["git"]


@pytest.mark.asyncio
async def test_mcp_management_refuses_a_missing_name_or_command() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "POST", "/api/mcp", {"command": "mcp"}))[0] == 400
    assert (await call(router, "POST", "/api/mcp", {"name": "x"}))[0] == 400
    assert conversation.added_mcp == []


@pytest.mark.asyncio
async def test_attachments_are_staged_and_listed() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "GET", "/api/attachments"))[1] == {"items": []}
    status, payload = await call(router, "POST", "/api/attachments", {"path": "notes.txt"})
    assert status == 200
    assert payload["name"] == "notes.txt"
    assert (await call(router, "GET", "/api/attachments"))[1]["items"][0]["name"] == "notes.txt"


@pytest.mark.asyncio
async def test_workspace_queries_and_diagnostics() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "GET", "/api/workspace/diff"))[1] == {"diff": "diff"}
    assert (await call(router, "GET", "/api/workspace/status"))[1] == {"status": "status"}
    status, payload = await call_query(router, "GET", "/api/workspace/diagnostics", {"path": ["x.py"]})
    assert (status, payload) == (200, {"diagnostics": "diagnostics:x.py"})
    assert (await call(router, "GET", "/api/workspace/diagnostics"))[0] == 400


@pytest.mark.asyncio
async def test_extensions_are_listed_and_custom_commands_expand() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    assert (await call(router, "GET", "/api/extensions"))[1] == {
        "commands": ["/review"],
        "skills": ["skill"],
        "plugins": ["plugin"],
    }
    status, payload = await call(router, "POST", "/api/extensions/expand", {"name": "/review", "arguments": "a"})
    assert (status, payload) == (200, {"text": "/review a"})
    assert conversation.expanded_commands == [("/review", "a")]


@pytest.mark.asyncio
async def test_memory_items_can_be_added_and_cleared() -> None:
    conversation = FakeConversation()
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "POST", "/api/memory/items", {"text": "remember this"})
    assert (status, payload["items"]) == (200, ["remember this"])
    assert conversation.remembered == ["remember this"]

    assert (await call(router, "DELETE", "/api/memory/items"))[0] == 200
    assert conversation.memory_items == []


@pytest.mark.asyncio
async def test_agents_are_listed_and_switched() -> None:
    conversation = FakeConversation()
    conversation.agents = [frontend.AgentSummary(name="build", provider="deepseek", model="m")]
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/agents")
    assert status == 200
    assert payload["current"]["name"] == "build"
    assert [item["name"] for item in payload["agents"]] == ["build"]

    assert (await call(router, "POST", "/api/agents/plan"))[0] == 200
    assert conversation.used_agents == ["plan"]


@pytest.mark.asyncio
async def test_session_scoped_commands_only_apply_to_the_active_session() -> None:
    conversation = FakeConversation(config=frontend.ConfigView(session_id="s1"))
    router, _hub, _runner = build(conversation)

    assert (await call(router, "POST", "/api/sessions/s2/compact", {"summary": "s"}))[0] == 400
    assert (await call(router, "POST", "/api/sessions/s1/compact", {"summary": "s"}))[0] == 200
    assert (await call(router, "POST", "/api/sessions/s1/fork", {"title": "branch"}))[1] == {"id": "fork-1"}
    assert (await call(router, "POST", "/api/sessions/s1/export", {"format": "markdown"}))[1] == {"path": ""}


@pytest.mark.asyncio
async def test_workflows_start_a_turn_with_the_shared_prompt() -> None:
    conversation = FakeConversation()
    router, _hub, runner = build(conversation)

    status, payload = await call(router, "POST", "/api/workflows/review")
    await runner.wait()

    assert (status, payload) == (202, {"accepted": True})
    assert conversation.queries == [frontend.WORKFLOW_PROMPTS["review"]]
    assert (await call(router, "POST", "/api/workflows/unknown"))[0] == 400


@pytest.mark.asyncio
async def test_instructions_are_read_from_the_active_session() -> None:
    conversation = FakeConversation(
        config=frontend.ConfigView(instruction_sources=("AGENTS.md", "CLAUDE.md"))
    )
    router, _hub, _runner = build(conversation)

    status, payload = await call(router, "GET", "/api/instructions")

    assert (status, payload) == (200, {"sources": ["AGENTS.md", "CLAUDE.md"]})
