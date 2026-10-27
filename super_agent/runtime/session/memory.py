"""Cross-session memory: the port, the switch, and the context it contributes.

Memory outlives the conversation it was written in, so it is not the session
repository's business. The repository owns one conversation's durable records;
the memory is whatever the application chose to keep, and where it lives is the
application's decision. So the runtime asks a port for the lines, and the
application hands over the backend its settings name. The runtime never learns
whether the lines live in the session store, in a file the user picked, or
nowhere at all.

Two rules keep the switch honest:

* switching memory off stops it being *used*, and the stored lines stay where
  they are, so switching it back on brings them back;
* switching it off also stops writes, and says so, rather than accepting a
  line that nothing would ever read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from super_agent.runtime.machine import ROLE_SYSTEM, Message

__all__ = [
    "MEMORY_SYSTEM_PREFIX",
    "Memory",
    "MemoryDisabled",
    "OffMemory",
    "Switch",
    "withMemoryContext",
]

#: The prefix that marks the memory system message, so it can be replaced rather
#: than accumulated on every remember.
MEMORY_SYSTEM_PREFIX = "Cross-session memory:\n"


class MemoryDisabled(Exception):
    """The memory is switched off, so there is nothing to write to."""


class Memory(Protocol):
    """Where the cross-session memory lives.

    An implementation decides the storage; callers only read and write lines.
    """

    @property
    def name(self) -> str:
        """The backend's name, which the interface shows as the memory's home."""
        ...

    @property
    def enabled(self) -> bool:
        """Whether the memory is in use right now."""
        ...

    def load(self) -> list[str]:
        """The stored lines, empty when there are none."""
        ...

    def save(self, items: Sequence[str]) -> None:
        """Replace the stored lines."""
        ...


class OffMemory:
    """No memory at all: the port exists, but nothing is kept."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return "off"

    @property
    def enabled(self) -> bool:
        return False

    def load(self) -> list[str]:
        return []

    def save(self, items: Sequence[str]) -> None:
        raise MemoryDisabled("cross-session memory is off")


class Switch:
    """The on/off switch in front of a memory backend.

    It is the same object whichever backend is behind it, so turning memory off
    and on never depends on where the lines are stored.
    """

    __slots__ = ("_enabled", "_memory")

    def __init__(self, memory: Memory, enabled: bool = True) -> None:
        self._memory = memory
        self._enabled = enabled

    @property
    def name(self) -> str:
        """The backend's name; the switch does not rename what it wraps."""
        return self._memory.name

    @property
    def enabled(self) -> bool:
        return self._enabled

    def setEnabled(self, enabled: bool) -> None:
        """Turn the memory on or off. The stored lines are untouched either way."""
        self._enabled = enabled

    def load(self) -> list[str]:
        if not self._enabled:
            return []
        return self._memory.load()

    def save(self, items: Sequence[str]) -> None:
        if not self._enabled:
            raise MemoryDisabled("cross-session memory is off")
        self._memory.save(items)


def withMemoryContext(messages: list[Message], items: list[str]) -> list[Message]:
    """Put the cross-session memory at the front, replacing any previous copy."""
    kept = [
        message
        for message in messages
        if message.role != ROLE_SYSTEM or not message.content.startswith(MEMORY_SYSTEM_PREFIX)
    ]
    if items:
        memory = Message(role=ROLE_SYSTEM, content=MEMORY_SYSTEM_PREFIX + "- " + "\n- ".join(items))
        return [memory, *kept]
    return kept
