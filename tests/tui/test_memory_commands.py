"""The ``/memory`` command: showing the memory, and switching it on and off.

The switch is the point. A memory a user cannot turn off is a memory they
cannot decline, so the command has to say what the state is, where the lines
live, and be able to change the state without a restart.
"""

from __future__ import annotations

import pytest

from super_agent.tui.commands import Config, Input, Model, Ports, new
from tests.tui.fakes import FakeFrontendPorts


def command_model(frontend_ports: FakeFrontendPorts) -> Model:
    """A command model wired to one fake frontend contract."""
    return new(
        Config(),
        Ports(
            sessions=frontend_ports,
            permissions=frontend_ports,
            mcp=frontend_ports,
            agents=frontend_ports,
            memory=frontend_ports,
            workspace=frontend_ports,
            extensions=frontend_ports,
            providers=frontend_ports,
        ),
    )


@pytest.mark.asyncio
async def test_the_command_says_where_the_memory_is_and_whether_it_is_on() -> None:
    """Before anything changes, the user is told the state and the place."""
    frontend_ports = FakeFrontendPorts()
    frontend_ports.memory_items = ["Prefer concise answers"]
    model = command_model(frontend_ports)

    _model, outcome, _command = await model.handle(Input(text="/memory"))

    assert outcome is not None
    assert outcome.status.startswith("Cross-session memory on")
    assert "store" in outcome.status
    assert "Prefer concise answers" in outcome.output


@pytest.mark.asyncio
async def test_the_command_switches_the_memory_off_and_on() -> None:
    """The switch is the command's own doing, not a restart away."""
    frontend_ports = FakeFrontendPorts()
    model = command_model(frontend_ports)

    _model, outcome, _command = await model.handle(Input(text="/memory off"))
    assert outcome is not None
    assert outcome.status == "Cross-session memory off"
    assert frontend_ports.memory_switches == [False]
    assert frontend_ports.memory_enabled() is False

    _model, outcome, _command = await model.handle(Input(text="/memory on"))
    assert outcome is not None
    assert outcome.status == "Cross-session memory on"
    assert frontend_ports.memory_switches == [False, True]


@pytest.mark.asyncio
async def test_an_empty_memory_says_so_instead_of_pretending() -> None:
    """Nothing remembered is a state worth reporting plainly."""
    frontend_ports = FakeFrontendPorts()
    model = command_model(frontend_ports)

    _model, outcome, _command = await model.handle(Input(text="/memory"))

    assert outcome is not None
    assert "nothing remembered" in outcome.status


@pytest.mark.asyncio
async def test_an_unknown_argument_is_a_usage_error() -> None:
    """A switch has two positions; anything else is a mistake, not a guess."""
    frontend_ports = FakeFrontendPorts()
    model = command_model(frontend_ports)

    _model, outcome, _command = await model.handle(Input(text="/memory maybe"))

    assert outcome is not None
    assert outcome.err == "Usage: /memory [on|off]"
    assert frontend_ports.memory_switches == []
