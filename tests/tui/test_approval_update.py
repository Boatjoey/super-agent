"""What the interactive CLI does with an approval while a turn waits.

An answer is a command, not a keystroke into a queue: it names the request it
answers, and the application refuses one that names nothing pending. These cases
pin the three things the interface owes the user — the menu remembers which request
it is showing, the choice reaches the port with that name, and a refusal is shown
rather than assumed to have worked.
"""

from __future__ import annotations

import pytest

from super_agent.tui import (
    APPROVE_ONCE,
    DENY_APPROVAL,
    App,
    ConversationError,
    Failure,
    PermissionRequest,
    ToolApprovalCleared,
    ToolApprovalRequested,
    ToolCall,
    runtime,
    update,
    updateConversationNotification,
)
from super_agent.tui.approval import Request
from tests.tui.fakes import ApprovalConversation, FakeConversation, new_app


def approval_request(request_id: str = "approval-7") -> ToolApprovalRequested:
    return ToolApprovalRequested(
        tool_call=ToolCall(name="bash", input="printf ok"),
        request=PermissionRequest(tool_name="bash", command_class="read-only", cwd="/repo", reason="risky"),
        request_id=request_id,
        batch_index=1,
        batch_total=1,
    )


def menu_request() -> Request:
    return Request(
        tool_name="bash",
        input="printf ok",
        command_class="read-only",
        cwd="/repo",
        touched_paths=(),
        reason="risky",
        batch_index=1,
        batch_total=1,
    )


async def open_menu(app: App, request_id: str = "approval-7") -> App:
    """Show the approval menu the way a running turn does."""
    app, _commands = updateConversationNotification(app, approval_request(request_id))
    return app


@pytest.mark.asyncio
async def test_the_menu_records_the_request_it_answers() -> None:
    app = new_app(ApprovalConversation())

    app = await open_menu(app, "approval-7")

    assert app.approval.active()
    assert app.approvalRequestID == "approval-7"


@pytest.mark.asyncio
async def test_a_decision_reaches_the_port_with_the_request_id() -> None:
    """The id is the whole point: without it the answer belongs to no request."""
    fake = ApprovalConversation()
    fake.pending_request_id = "approval-7"
    app = new_app(fake)
    app.approvalRequestID = "approval-7"
    app.approval.open(menu_request())

    app, _commands = await update(app, runtime.KeyMsg(key="1"))

    assert fake.approvals == [("approval-7", APPROVE_ONCE)]


@pytest.mark.asyncio
async def test_a_refused_decision_is_shown_instead_of_assumed() -> None:
    """The menu closes and the decision was never applied: say which, and why."""
    fake = FakeConversation()
    app = new_app(fake)
    app.approvalRequestID = "approval-gone"
    app.approval.open(menu_request())

    app, _commands = await update(app, runtime.KeyMsg(key="3"))

    assert fake.approvals == [("approval-gone", DENY_APPROVAL)]
    assert "not applied" in app.err
    assert "no tool call is waiting" in app.err


@pytest.mark.asyncio
async def test_a_cleared_approval_forgets_the_request() -> None:
    app = await open_menu(new_app(ApprovalConversation()), "approval-7")

    app, _commands = updateConversationNotification(app, ToolApprovalCleared(request_id="approval-7"))

    assert app.approvalRequestID == ""
    assert not app.approval.active()


@pytest.mark.asyncio
async def test_a_failure_is_shown_and_a_cancellation_is_not_shouted_about() -> None:
    """The code says whether the input was accepted; the message is display-ready."""
    app = new_app(FakeConversation())

    app, _commands = updateConversationNotification(
        app, ConversationError(failure=Failure(message="provider refused", code="failed", operation="run_turn"))
    )
    assert app.err == "provider refused"

    app.err = ""
    app, _commands = updateConversationNotification(
        app, ConversationError(failure=Failure(message="cancelled", code="cancelled", operation="run_turn"))
    )
    assert app.err == ""
