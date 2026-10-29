"""A turn runner needs interaction capabilities without the full front end."""

from __future__ import annotations

import asyncio

import pytest

from super_agent import frontend
from super_agent.web import EventHub, TurnRunner
from super_agent.web.turns import NoPendingApproval
from tests.fakes.frontend import AwaitingApprovalFrontendPorts, InteractionOnly


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interaction_without_management_drives_a_turn_to_its_final_snapshot(cancel: bool) -> None:
    frontend_ports = AwaitingApprovalFrontendPorts()
    interaction: frontend.AgentInteractionPort = InteractionOnly(frontend_ports)
    hub = EventHub()
    subscription = hub.subscribe()
    runner = TurnRunner(interaction=interaction, hub=hub)

    attachment = await interaction.attach("notes.txt")
    assert attachment.name == "notes.txt"
    assert await interaction.pending_attachments() == (attachment,)
    await runner.start_turn("hello")
    await asyncio.wait_for(frontend_ports.started.wait(), timeout=5)
    assert (await runner.steer("adjust")).status == frontend.STEERING_HELD
    assert (await runner.queue("later")).status == frontend.QUEUED
    if cancel:
        await runner.cancel()
        assert frontend_ports.cancellations == 1
    else:
        with pytest.raises(NoPendingApproval):
            await runner.approve("once", "stale")
        await runner.approve("once", "approval-1")
        with pytest.raises(NoPendingApproval):
            await runner.approve("once", "approval-1")
    await asyncio.wait_for(runner.wait(), timeout=5)

    events = [await asyncio.wait_for(subscription.get(), timeout=5)]
    while events[-1]["kind"] != "Snapshot":
        events.append(await asyncio.wait_for(subscription.get(), timeout=5))
    kinds = [event["kind"] for event in events]
    assert kinds[:2] == ["TurnStarted", "ToolApprovalRequested"]
    assert kinds[-2:] == ["TurnFinished", "Snapshot"]
    assert ("ToolApprovalCleared" in kinds) is (not cancel)
    assert events[-1] == runner.snapshot_event()
    assert frontend_ports.queries == ["hello"]
    assert frontend_ports.steers == ["adjust"]
    assert frontend_ports.queued == ["later"]
    assert not runner.running
    subscription.aclose()
