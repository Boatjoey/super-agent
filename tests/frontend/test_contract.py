"""The contract's own invariants.

A front end may rely on these: the notification set is closed, a channel has one
end, and a receipt says only what is true at submission time.
"""

from __future__ import annotations

import asyncio

import pytest

from super_agent import frontend
from super_agent.frontend import notifications, wire


def test_the_notification_set_is_closed_to_this_package() -> None:
    """A transport cannot extend the set: unknown kinds would never be mapped."""
    with pytest.raises(TypeError, match="sealed"):
        type("Extra", (frontend.ConversationNotification,), {"kind": "Extra"})


def test_the_kind_list_matches_the_declared_kinds() -> None:
    declared = {
        value.kind
        for name, value in vars(notifications).items()
        if isinstance(value, type)
        and issubclass(value, frontend.ConversationNotification)
        and value is not frontend.ConversationNotification
        and name != "ConversationNotification"
    }
    assert declared == set(frontend.NOTIFICATION_KINDS)
    assert len(frontend.NOTIFICATION_KINDS) == 11


def test_a_receipt_is_held_or_rejected_and_nothing_else() -> None:
    held = frontend.SteeringReceipt.held("steer-1")
    assert (held.input_id, held.status, held.reason) == ("steer-1", frontend.STEERING_HELD, "")

    rejected = frontend.SteeringReceipt.rejected("steer-2", "no turn is running")
    assert rejected.status == frontend.REJECTED
    assert rejected.reason == "no turn is running"


def test_a_queued_receipt_says_queued_or_rejected_and_nothing_else() -> None:
    """Neither status is delivery: the turn it becomes is reported separately."""
    queued = frontend.QueuedReceipt.queued("queue-1")
    assert (queued.input_id, queued.status, queued.reason) == ("queue-1", frontend.QUEUED, "")

    rejected = frontend.QueuedReceipt.rejected("queue-2", "no turn is running")
    assert rejected.status == frontend.REJECTED
    assert rejected.reason == "no turn is running"


@pytest.mark.asyncio
async def test_a_channel_delivers_in_order_and_then_ends() -> None:
    channel: frontend.Channel[str] = frontend.Channel()
    channel.put("first")
    channel.put("second")
    channel.close()

    assert await channel.get() == "first"
    assert await channel.get() == "second"
    assert await channel.get() is None


@pytest.mark.asyncio
async def test_a_send_after_the_close_is_dropped_rather_than_queued() -> None:
    channel: frontend.Channel[str] = frontend.Channel()
    channel.close()
    channel.put("late")

    assert await channel.get() is None


@pytest.mark.asyncio
async def test_a_cancellation_is_a_value_that_can_be_waited_on() -> None:
    cancellation = frontend.Cancellation()
    assert cancellation.cancelled is False

    cancellation.cancel()
    cancellation.cancel()
    await asyncio.wait_for(cancellation.wait(), timeout=1)

    assert cancellation.cancelled is True


def test_the_wire_names_every_notification_kind() -> None:
    """Every kind must survive the projection, or a transport silently loses it."""
    samples = {
        "AgentStatusChanged": frontend.AgentStatusChanged(status=frontend.AgentStatus(label="Idle")),
        "ToolApprovalRequested": frontend.ToolApprovalRequested(
            tool_call=frontend.ToolCall(id="c1", name="run_command", input="{}"),
            request=frontend.PermissionRequest(tool_name="run_command"),
        ),
        "ToolApprovalCleared": frontend.ToolApprovalCleared(),
        "StreamChunkReceived": frontend.StreamChunkReceived(
            message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="hi")
        ),
        "MessageAppended": frontend.MessageAppended(message=frontend.Message(role=frontend.ROLE_USER, content="hi")),
        "SteeringAccepted": frontend.SteeringAccepted(input_id="steer-1", step=2),
        "SteeringWithdrawn": frontend.SteeringWithdrawn(input_id="steer-2"),
        "QueuedInputAccepted": frontend.QueuedInputAccepted(input_id="queue-1", turn=3),
        "QueuedInputWithdrawn": frontend.QueuedInputWithdrawn(input_id="queue-2"),
        "UsageReported": frontend.UsageReported(usage=frontend.ContextUsage(total_tokens=12)),
        "ConversationError": frontend.ConversationError(
            failure=frontend.Failure(message="boom", code=frontend.FAILED, operation="run_turn")
        ),
    }
    assert set(samples) == set(frontend.NOTIFICATION_KINDS)
    for kind, notification in samples.items():
        assert wire.notification_to_json(notification)["kind"] == kind


def test_a_failure_without_a_message_is_named_by_its_type() -> None:
    """An empty string would read as "nothing happened", which is a lie."""
    assert wire.error_text(RuntimeError()) == "RuntimeError"
    assert wire.error_text(RuntimeError("boom")) == "boom"
    assert wire.error_text(None) == ""


def test_success_carries_no_failure_at_all() -> None:
    """An object of four empty fields would look like a failure that lost its text."""
    assert wire.failure_to_json(None) is None
    failure = frontend.Failure(message="boom", code=frontend.CANCELLED, operation="cancel")
    assert wire.failure_to_json(failure) == {
        "message": "boom",
        "code": "cancelled",
        "operation": "cancel",
        "request_id": "",
    }


def test_a_view_projects_the_state_a_front_end_rebuilds_from() -> None:
    view = frontend.ConversationView(
        agent_status=frontend.AgentStatus(label="WaitingApproval", awaiting_approval=True),
        messages=(frontend.Message(role=frontend.ROLE_USER, content="hi"),),
        pending_tool=frontend.ToolCall(id="c1", name="write_file", input='{"path": "a"}'),
        pending_permission=frontend.PermissionRequest(tool_name="write_file", touched_paths=("/w/a",)),
        pending_tool_batch_index=0,
        pending_tool_batch_total=2,
        streaming_message=frontend.Message(role=frontend.ROLE_ASSISTANT, content="par"),
    )

    payload = wire.view_to_json(view)

    assert payload["agent_status"]["awaiting_approval"] is True
    assert payload["messages"][0] == {
        "role": "user",
        "content": "hi",
        "reasoning_content": "",
        "tool_call_id": "",
        "tool_name": "",
        "tool_calls": [],
        "interrupted": False,
        "attachments": [],
    }
    assert payload["pending_tool"]["name"] == "write_file"
    assert payload["pending_permission"]["touched_paths"] == ["/w/a"]
    assert payload["pending_tool_batch_total"] == 2
    assert payload["streaming_message"]["content"] == "par"


def test_the_approval_decisions_are_the_runtime_spellings() -> None:
    assert (str(frontend.APPROVE_ONCE), str(frontend.APPROVE_ALWAYS), str(frontend.DENY)) == ("once", "always", "deny")
