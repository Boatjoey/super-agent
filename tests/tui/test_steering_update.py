"""What the interactive CLI does with an input submitted mid-turn.

Enter during a turn is a steering submission, not a cancellation: the turn keeps
its step, the runtime holds the input, and the acceptance arrives later. These
cases pin the three things the interface owes the user in that window — the text
is not lost, the turn is not cancelled, and "waiting" is never shown as "taken
up" until the runtime says a step took it.
"""

from __future__ import annotations

import pytest

from super_agent.tui import (
    App,
    Cancellation,
    SteeringAccepted,
    SteeringReceipt,
    SteeringWithdrawn,
    runtime,
    update,
    updateConversationNotification,
)
from tests.tui.fakes import FakeFrontendPorts, new_app

TEXT = "also check the tests"


async def type_and_submit(app: App, text: str) -> tuple[App, tuple[runtime.Command[object], ...]]:
    """Type ``text`` into the composer while a turn runs, then press Enter.

    The composer decides Enter means steering by asking the app whether a turn is
    live, which is exactly the state a real turn leaves behind.
    """
    app.cancellation = Cancellation()
    app.composer.set_turn_running(True)
    for character in text:
        app, _commands = await update(app, runtime.KeyMsg(key=character))
    return await update(app, runtime.KeyMsg(key="enter"))


@pytest.mark.asyncio
async def test_enter_during_a_turn_steers_instead_of_cancelling() -> None:
    """The running turn is left alone; the input goes to it, not to a new one."""
    fake = FakeFrontendPorts()
    app = new_app(fake)

    app, _commands = await type_and_submit(app, TEXT)

    assert fake.steers == [TEXT]
    assert fake.cancellations == 0
    assert fake.queries == []
    assert app.status == "Steering · waiting for the next step"
    assert app.composer.draft() == ""


@pytest.mark.asyncio
async def test_a_refused_submission_keeps_the_draft_and_shows_the_reason() -> None:
    """Nothing was accepted, so nothing may be cleared or promised."""
    fake = FakeFrontendPorts(receipts=[SteeringReceipt.rejected("steer-1", "no turn is running")])
    app = new_app(fake)

    app, _commands = await type_and_submit(app, TEXT)

    assert app.composer.draft() == TEXT
    assert "no turn is running" in app.err
    assert app.status == ""


@pytest.mark.asyncio
async def test_acceptance_names_the_step_that_took_the_input_up() -> None:
    fake = FakeFrontendPorts(receipts=[SteeringReceipt.held("steer-1")])
    app = new_app(fake)
    app, _commands = await type_and_submit(app, TEXT)

    app, _commands = updateConversationNotification(app, SteeringAccepted(input_id="steer-1", step=2))

    assert app.status == "Steering accepted at step 2"
    assert app.err == ""


@pytest.mark.asyncio
async def test_a_withdrawn_input_is_reported_rather_than_left_waiting() -> None:
    fake = FakeFrontendPorts(receipts=[SteeringReceipt.held("steer-1")])
    app = new_app(fake)
    app, _commands = await type_and_submit(app, TEXT)

    app, _commands = updateConversationNotification(app, SteeringWithdrawn(input_id="steer-1"))

    assert "discarded" in app.err
