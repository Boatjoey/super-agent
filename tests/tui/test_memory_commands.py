"""The ``/memory`` command: showing the memory, and switching it on and off.

The switch is the point. A memory a user cannot turn off is a memory they
cannot decline, so the command has to say what the state is, where the lines
live, and be able to change the state without a restart.
"""

from __future__ import annotations

import pytest

from super_agent.tui.commands import Config, Input, Model, Ports, new
from tests.tui.fakes import FakeConversation


def command_model(conversation: FakeConversation) -> Model:
    """A command model wired to one fake conversation."""
    return new(
        Config(),
        Ports(
            sessions=conversation,
            permissions=conversation,
            mcp=conversation,
            agents=conversation,
            memory=conversation,
            workspace=conversation,
            extensions=conversation,
        ),
    )


@pytest.mark.asyncio
async def test_the_command_says_where_the_memory_is_and_whether_it_is_on() -> None:
    """Before anything changes, the user is told the state and the place."""
    conversation = FakeConversation()
    conversation.memory_items = ["Prefer concise answers"]
    model = command_model(conversation)

    _model, outcome, _command = await model.handle(Input(text="/memory"))

    assert outcome is not None
    assert outcome.status.startswith("Cross-session memory on")
    assert "store" in outcome.status
    assert "Prefer concise answers" in outcome.output


@pytest.mark.asyncio
async def test_the_command_switches_the_memory_off_and_on() -> None:
    """The switch is the command's own doing, not a restart away."""
    conversation = FakeConversation()
    model = command_model(conversation)

    _model, outcome, _command = await model.handle(Input(text="/memory off"))
    assert outcome is not None
    assert outcome.status == "Cross-session memory off"
    assert conversation.memory_switches == [False]
    assert conversation.memory_enabled() is False

    _model, outcome, _command = await model.handle(Input(text="/memory on"))
    assert outcome is not None
    assert outcome.status == "Cross-session memory on"
    assert conversation.memory_switches == [False, True]


@pytest.mark.asyncio
async def test_an_empty_memory_says_so_instead_of_pretending() -> None:
    """Nothing remembered is a state worth reporting plainly."""
    conversation = FakeConversation()
    model = command_model(conversation)

    _model, outcome, _command = await model.handle(Input(text="/memory"))

    assert outcome is not None
    assert "nothing remembered" in outcome.status


@pytest.mark.asyncio
async def test_an_unknown_argument_is_a_usage_error() -> None:
    """A switch has two positions; anything else is a mistake, not a guess."""
    conversation = FakeConversation()
    model = command_model(conversation)

    _model, outcome, _command = await model.handle(Input(text="/memory maybe"))

    assert outcome is not None
    assert outcome.err == "Usage: /memory [on|off]"
    assert conversation.memory_switches == []
