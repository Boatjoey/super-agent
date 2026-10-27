"""The cross-session memory: the port, the switch, and what the session does.

The memory is a separate dependency from the session repository, so these cases
are about the seam: a backend that is not the store still works, a switch that
is off refuses writes instead of losing them, and the conversation context
follows the switch in both directions.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from super_agent.runtime.engine import new_engine_with_executor
from super_agent.runtime.protocol.types import ROLE_SYSTEM, ROLE_USER, Message
from super_agent.runtime.session import (
    MEMORY_SYSTEM_PREFIX,
    Memory,
    MemoryDisabled,
    OffMemory,
    Session,
    Switch,
    new_session,
    withMemoryContext,
)
from tests.fakes.execution import StaticReplyExecutor


class ListMemory:
    """A memory kept in a list, so a test can watch what the port is asked for."""

    def __init__(self, items: list[str] | None = None) -> None:
        self.items = list(items or [])
        self.writes: list[list[str]] = []

    @property
    def name(self) -> str:
        return "list"

    @property
    def enabled(self) -> bool:
        return True

    def load(self) -> list[str]:
        return list(self.items)

    def save(self, items: Sequence[str]) -> None:
        self.writes.append(list(items))
        self.items = list(items)


async def session_with(memory: Memory) -> Session:
    """A session whose memory is the given port."""
    engine = new_engine_with_executor(
        StaticReplyExecutor(),
        [Message(role=ROLE_SYSTEM, content="rules"), Message(role=ROLE_USER, content="hello")],
    )
    await engine.ready()
    return new_session(engine, memory=memory)


def test_the_context_replaces_the_previous_copy_instead_of_stacking() -> None:
    """Two memories must not become two system messages."""
    messages = [
        Message(role=ROLE_SYSTEM, content=MEMORY_SYSTEM_PREFIX + "- old"),
        Message(role=ROLE_USER, content="hello"),
    ]

    once = withMemoryContext(messages, ["new"])
    twice = withMemoryContext(once, ["newer"])

    assert len(twice) == 2
    assert twice[0].content.startswith(MEMORY_SYSTEM_PREFIX)
    assert "newer" in twice[0].content
    assert "old" not in twice[0].content


def test_an_empty_memory_removes_the_context_entirely() -> None:
    """Turning the memory off takes the lines out of the conversation."""
    messages = [
        Message(role=ROLE_SYSTEM, content=MEMORY_SYSTEM_PREFIX + "- old"),
        Message(role=ROLE_USER, content="hi"),
    ]

    assert withMemoryContext(messages, []) == [Message(role=ROLE_USER, content="hi")]


def test_a_switched_off_memory_reads_nothing_and_refuses_writes() -> None:
    """The switch hides the lines and says so, rather than dropping them."""
    backend = ListMemory(["a line"])
    switch = Switch(backend, enabled=False)

    assert switch.load() == []
    assert switch.enabled is False
    assert switch.name == "list"
    with pytest.raises(MemoryDisabled):
        switch.save(["another line"])
    # The backend was never asked to write: nothing was lost, nothing was kept.
    assert backend.writes == []


def test_a_switched_off_memory_keeps_what_was_already_stored() -> None:
    """Switching off stops the memory being used, not the memory being kept."""
    backend = ListMemory(["a line"])
    switch = Switch(backend, enabled=False)

    switch.setEnabled(True)

    assert switch.load() == ["a line"]


def test_a_memory_with_no_backend_at_all_refuses_writes() -> None:
    """The port exists even when nothing is behind it."""
    memory = OffMemory()

    assert memory.enabled is False
    assert memory.load() == []
    assert memory.name == "off"
    with pytest.raises(MemoryDisabled):
        memory.save(["a line"])


@pytest.mark.asyncio
async def test_the_session_remembers_through_the_port() -> None:
    """The session asks the port, so a backend that is not the store still works."""
    backend = ListMemory()
    session = await session_with(Switch(backend))

    await session.remember("Prefer concise answers")

    assert session.memories() == ["Prefer concise answers"]
    assert backend.items == ["Prefer concise answers"]
    messages = session.snapshot().messages
    assert "Prefer concise answers" in messages[0].content


@pytest.mark.asyncio
async def test_the_session_refuses_to_remember_when_the_memory_is_off() -> None:
    """A line written into a memory nobody reads would be a lie."""
    backend = ListMemory()
    session = await session_with(Switch(backend, enabled=False))

    with pytest.raises(MemoryDisabled):
        await session.remember("Prefer concise answers")

    assert backend.writes == []


@pytest.mark.asyncio
async def test_the_context_follows_the_switch_in_both_directions() -> None:
    """Turning the memory off takes the lines out; turning it on puts them back."""
    backend = ListMemory(["Prefer concise answers"])
    switch = Switch(backend, enabled=True)
    session = await session_with(switch)

    assert "Prefer concise answers" not in session.snapshot().messages[0].content

    switch.setEnabled(False)
    await session.refresh_memory()
    off = session.snapshot().messages
    assert all(not message.content.startswith(MEMORY_SYSTEM_PREFIX) for message in off)

    switch.setEnabled(True)
    await session.refresh_memory()
    on = session.snapshot().messages
    assert on[0].content.startswith(MEMORY_SYSTEM_PREFIX)
    assert "Prefer concise answers" in on[0].content
