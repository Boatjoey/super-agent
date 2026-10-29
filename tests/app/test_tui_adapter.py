"""The interactive CLI adapter's mapping of runtime values to presentation values.

The adapter is the one place runtime values become presentation values, so the
test drives it through the engine: an unready engine is ``Initializing``, and a
ready one is ``Idle`` with nothing pending.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from super_agent import runtime, tui
from super_agent.app import new_terminal_conversation
from super_agent.app.tui_adapter import to_conversation_notification
from tests.fakes.model import ScriptedModel


@pytest.mark.asyncio
async def test_tui_adapter_maps_runtime_state() -> None:
    # The engine is built with nil ports: the default executor wraps a nil model
    # and a nil tool runner, which is the same engine for a test that only reads
    # its state.
    engine = runtime.new_engine(None, None, None)
    frontend_ports = new_terminal_conversation(runtime.new_session(engine))

    status = frontend_ports.snapshot().agent_status
    assert status.label == "Initializing"
    assert status.busy is True

    await engine.ready()

    status = frontend_ports.snapshot().agent_status
    assert status.label == "Idle"
    assert status.busy is False
    assert status.awaiting_approval is False


def test_tui_adapter_maps_reported_usage() -> None:
    """The provider's counts cross the boundary unchanged, as the CLI's own DTO."""
    notification = to_conversation_notification(
        runtime.UsageReported(usage=runtime.Usage(input_tokens=11, output_tokens=7, total_tokens=18))
    )

    assert notification == tui.UsageReported(usage=tui.ContextUsage(input_tokens=11, output_tokens=7, total_tokens=18))


@pytest.mark.asyncio
async def test_tui_adapter_delivers_provider_usage_through_a_turn() -> None:
    """A reported usage reaches the interface while the turn runs.

    The whole path is exercised — engine, session notification, adapter, channel —
    because a mapping that is never reached is not a working notification.
    """
    model = ScriptedModel(
        [
            runtime.ModelResponse(
                content="hello",
                usage=runtime.Usage(input_tokens=11, output_tokens=7, total_tokens=18),
            )
        ]
    )
    engine = runtime.new_engine(model, None, None)
    await engine.ready()
    frontend_ports = new_terminal_conversation(runtime.new_session(engine))
    notifications: tui.Channel[tui.ConversationNotification] = tui.Channel()

    error = await frontend_ports.run_turn("hi", notifications, tui.Cancellation())
    assert error is None

    seen: list[tui.ConversationNotification] = []
    while (notification := await notifications.get()) is not None:
        seen.append(notification)

    assert [item for item in seen if isinstance(item, tui.UsageReported)] == [
        tui.UsageReported(usage=tui.ContextUsage(input_tokens=11, output_tokens=7, total_tokens=18))
    ]


# --- steering across the boundary --------------------------------------------


class SteeringModel:
    """Submits one in-turn input during its first call, then answers normally."""

    def __init__(self, responses: list[runtime.ModelResponse]) -> None:
        self.responses: list[runtime.ModelResponse] = list(responses)
        self.steer: Callable[[], Awaitable[None]] | None = None
        self.calls = 0

    async def next(
        self,
        ctx: object,
        messages: list[runtime.Message],
        tools: list[runtime.ToolSpec],
        on_stream_chunk: Callable[[runtime.StreamChunk], None],
    ) -> runtime.ModelResponse:
        del ctx, messages, tools, on_stream_chunk
        index = self.calls
        self.calls += 1
        if index == 0:
            assert self.steer is not None
            await self.steer()
        return self.responses[index]


def test_tui_adapter_maps_steering_receipts() -> None:
    """Acceptance and withdrawal cross the boundary as the CLI's own kinds."""
    assert to_conversation_notification(runtime.SteeringAccepted(input_id="steer-1", step=3)) == tui.SteeringAccepted(
        input_id="steer-1", step=3
    )
    assert to_conversation_notification(runtime.SteeringWithdrawn(input_id="steer-2")) == tui.SteeringWithdrawn(
        input_id="steer-2"
    )


@pytest.mark.asyncio
async def test_tui_adapter_refuses_steering_with_no_turn_running() -> None:
    """Nothing is running, so the input belongs nowhere: a value, not an exception."""
    engine = runtime.new_engine(None, None, None)
    await engine.ready()
    frontend_ports = new_terminal_conversation(runtime.new_session(engine))

    receipt = await frontend_ports.steer("also check the tests")

    assert receipt.status == tui.REJECTED
    assert receipt.reason == "no turn is running"
    assert receipt.input_id.startswith("steer-")


@pytest.mark.asyncio
async def test_tui_adapter_holds_a_steered_input_and_names_its_step() -> None:
    """The receipt says held now; the notification says which step took it up."""
    model = SteeringModel([runtime.ModelResponse(content="first"), runtime.ModelResponse(content="second")])
    engine = runtime.new_engine(model, None, None)
    await engine.ready()
    frontend_ports = new_terminal_conversation(runtime.new_session(engine))
    notifications: tui.Channel[tui.ConversationNotification] = tui.Channel()

    receipts: list[tui.SteeringReceipt] = []

    async def steer() -> None:
        receipts.append(await frontend_ports.steer("also check the tests"))

    model.steer = steer

    error = await frontend_ports.run_turn("hi", notifications, tui.Cancellation())
    assert error is None

    assert len(receipts) == 1
    assert receipts[0].status == tui.STEERING_HELD

    seen: list[tui.ConversationNotification] = []
    while (notification := await notifications.get()) is not None:
        seen.append(notification)

    assert [item for item in seen if isinstance(item, tui.SteeringAccepted)] == [
        tui.SteeringAccepted(input_id=receipts[0].input_id, step=2)
    ]
