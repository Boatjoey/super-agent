"""The application's mapping of runtime values to presentation values.

The application boundary is the one place runtime values become presentation
values, so the test drives it through the engine: an unready engine is
``Initializing``, and a ready one is ``Idle`` with nothing pending.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from super_agent import frontend
from super_agent.application.agent_application import new_agent_application
from super_agent.application.presentation import to_conversation_notification
from super_agent.runtime.engine import new_engine
from super_agent.runtime.protocol.types import Message, ModelResponse, StreamChunk, ToolSpec, Usage
from super_agent.runtime.session import SteeringAccepted, SteeringWithdrawn, UsageReported, new_session
from tests.fakes.model import ScriptedModel


@pytest.mark.asyncio
async def test_application_maps_runtime_state() -> None:
    # The engine is built with nil ports: the default executor wraps a nil model
    # and a nil tool runner, which is the same engine for a test that only reads
    # its state.
    engine = new_engine(None, None, None)
    frontend_ports = new_agent_application(new_session(engine))

    status = frontend_ports.snapshot().agent_status
    assert status.label == "Initializing"
    assert status.busy is True

    await engine.ready()

    status = frontend_ports.snapshot().agent_status
    assert status.label == "Idle"
    assert status.busy is False
    assert status.awaiting_approval is False


def test_application_maps_reported_usage() -> None:
    """The provider's counts cross the boundary unchanged, as the contract's own DTO."""
    notification = to_conversation_notification(
        UsageReported(usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18))
    )

    assert notification == frontend.UsageReported(
        usage=frontend.ContextUsage(input_tokens=11, output_tokens=7, total_tokens=18)
    )


@pytest.mark.asyncio
async def test_application_delivers_provider_usage_through_a_turn() -> None:
    """A reported usage reaches the interface while the turn runs.

    The whole path is exercised — engine, session notification, application,
    channel — because a mapping that is never reached is not a working
    notification.
    """
    model = ScriptedModel(
        [
            ModelResponse(
                content="hello",
                usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18),
            )
        ]
    )
    engine = new_engine(model, None, None)
    await engine.ready()
    frontend_ports = new_agent_application(new_session(engine))
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()

    error = await frontend_ports.run_turn("hi", notifications, frontend.Cancellation())
    assert error is None

    seen: list[frontend.ConversationNotification] = []
    while (notification := await notifications.get()) is not None:
        seen.append(notification)

    assert [item for item in seen if isinstance(item, frontend.UsageReported)] == [
        frontend.UsageReported(usage=frontend.ContextUsage(input_tokens=11, output_tokens=7, total_tokens=18))
    ]


# --- steering across the boundary --------------------------------------------


class SteeringModel:
    """Submits one in-turn input during its first call, then answers normally."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses: list[ModelResponse] = list(responses)
        self.steer: Callable[[], Awaitable[None]] | None = None
        self.calls = 0

    async def next(
        self,
        ctx: object,
        messages: list[Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        del ctx, messages, tools, on_stream_chunk
        index = self.calls
        self.calls += 1
        if index == 0:
            assert self.steer is not None
            await self.steer()
        return self.responses[index]


def test_application_maps_steering_receipts() -> None:
    """Acceptance and withdrawal cross the boundary as the contract's own kinds."""
    assert to_conversation_notification(SteeringAccepted(input_id="steer-1", step=3)) == frontend.SteeringAccepted(
        input_id="steer-1", step=3
    )
    assert to_conversation_notification(SteeringWithdrawn(input_id="steer-2")) == frontend.SteeringWithdrawn(
        input_id="steer-2"
    )


@pytest.mark.asyncio
async def test_application_refuses_steering_with_no_turn_running() -> None:
    """Nothing is running, so the input belongs nowhere: a value, not an exception."""
    engine = new_engine(None, None, None)
    await engine.ready()
    frontend_ports = new_agent_application(new_session(engine))

    receipt = await frontend_ports.steer("also check the tests")

    assert receipt.status == frontend.REJECTED
    assert receipt.reason == "no turn is running"
    assert receipt.input_id.startswith("steer-")


@pytest.mark.asyncio
async def test_application_holds_a_steered_input_and_names_its_step() -> None:
    """The receipt says held now; the notification says which step took it up."""
    model = SteeringModel([ModelResponse(content="first"), ModelResponse(content="second")])
    engine = new_engine(model, None, None)
    await engine.ready()
    frontend_ports = new_agent_application(new_session(engine))
    notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()

    receipts: list[frontend.SteeringReceipt] = []

    async def steer() -> None:
        receipts.append(await frontend_ports.steer("also check the tests"))

    model.steer = steer

    error = await frontend_ports.run_turn("hi", notifications, frontend.Cancellation())
    assert error is None

    assert len(receipts) == 1
    assert receipts[0].status == frontend.STEERING_HELD

    seen: list[frontend.ConversationNotification] = []
    while (notification := await notifications.get()) is not None:
        seen.append(notification)

    assert [item for item in seen if isinstance(item, frontend.SteeringAccepted)] == [
        frontend.SteeringAccepted(input_id=receipts[0].input_id, step=2)
    ]
