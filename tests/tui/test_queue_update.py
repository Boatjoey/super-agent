"""What the interactive CLI does with an input queued for the next turn.

Tab during a turn is not a submission of the current turn and not steering either:
the application holds the input for the turn after this one and starts that turn
itself when this one ends. These cases pin the three things the footer owes the
user in that window — the text is not lost, the current turn is not disturbed, and
"queued" is never shown as "sent" until the application says a turn took it up.
"""

from __future__ import annotations

import pytest

from super_agent.tui import (
    App,
    Cancellation,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    QueuedReceipt,
    runtime,
    update,
    updateConversationNotification,
)
from tests.tui.fakes import FakeConversation, new_app

TEXT = "then run the tests"


async def type_and_queue(app: App, text: str) -> tuple[App, tuple[runtime.Command[object], ...]]:
    """Type ``text`` into the composer while a turn runs, then press Tab.

    The composer decides Tab means queueing by asking the app whether a turn is
    live, which is exactly the state a real turn leaves behind.
    """
    app.cancellation = Cancellation()
    app.composer.set_turn_running(True)
    for character in text:
        app, _commands = await update(app, runtime.KeyMsg(key=character))
    return await update(app, runtime.KeyMsg(key="tab"))


@pytest.mark.asyncio
async def test_tab_during_a_turn_queues_through_the_application() -> None:
    """The queue is the application's; the footer only shows what it accepted."""
    fake = FakeConversation()
    app = new_app(fake)

    app, _commands = await type_and_queue(app, TEXT)

    assert fake.queued == [TEXT]
    assert fake.steers == []
    assert fake.cancellations == 0
    assert fake.queries == []
    assert app.status == "Queued · waiting for the next turn"
    assert app.composer.draft() == ""
    assert [entry.text for entry in app.composer.queued] == [TEXT]


@pytest.mark.asyncio
async def test_a_refused_queue_keeps_the_draft_and_shows_the_reason() -> None:
    """Nothing was accepted, so nothing may be cleared or promised."""
    fake = FakeConversation(queued=[QueuedReceipt.rejected("queue-1", "no turn is running")])
    app = new_app(fake)

    app, _commands = await type_and_queue(app, TEXT)

    assert app.composer.draft() == TEXT
    assert app.composer.queued == []
    assert "no turn is running" in app.err
    assert app.status == ""


@pytest.mark.asyncio
async def test_the_turn_that_takes_the_input_up_clears_the_footer() -> None:
    fake = FakeConversation()
    app = new_app(fake)
    app, _commands = await type_and_queue(app, TEXT)
    input_id = app.composer.queued[0].id

    app, _commands = updateConversationNotification(app, QueuedInputAccepted(input_id=input_id, turn=2))

    assert app.composer.queued == []
    assert app.status == "Queued input started turn 2"
    assert app.err == ""


@pytest.mark.asyncio
async def test_a_withdrawn_input_leaves_the_footer_and_says_why() -> None:
    """A cancelled turn takes the queue with it, so the entry cannot keep waiting."""
    fake = FakeConversation()
    app = new_app(fake)
    app, _commands = await type_and_queue(app, TEXT)
    input_id = app.composer.queued[0].id

    app, _commands = updateConversationNotification(app, QueuedInputWithdrawn(input_id=input_id))

    assert app.composer.queued == []
    assert "cancelled" in app.err


@pytest.mark.asyncio
async def test_a_finished_submission_does_not_start_the_queued_input_here() -> None:
    """Sequencing belongs to the application: the footer must not run turn two."""
    fake = FakeConversation()
    app = new_app(fake)
    app, _commands = await type_and_queue(app, TEXT)

    from super_agent.tui import finishSubmit

    app, commands = finishSubmit(app, None)

    assert commands == ()
    assert fake.queries == []
    assert app.composer.turnRunning is False


@pytest.mark.asyncio
async def test_a_command_is_not_queued() -> None:
    fake = FakeConversation()
    app = new_app(fake)

    app, _commands = await type_and_queue(app, "/diff")

    assert fake.queued == []
    assert "Slash commands are unavailable" in app.err
