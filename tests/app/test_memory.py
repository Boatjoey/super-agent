"""Choosing where the memory lives, and the switch that turns it on and off.

The settings name a backend and the state of the switch; the application turns
that into a port and keeps the switch honest across restarts. These cases cover
the decisions a user makes with a text file, so they are about what the
application does with the file — not about the file format itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from super_agent.app.config import MemorySettings, load_settings_file, save_settings_file
from super_agent.app.memory import MemoryController, openMemory, setMemoryEnabled
from super_agent.runtime.engine import new_engine_with_executor
from super_agent.runtime.protocol.types import ROLE_SYSTEM, ROLE_USER, Message
from super_agent.runtime.session import (
    MEMORY_SYSTEM_PREFIX,
    Memory,
    MemoryDisabled,
    Session,
    Switch,
    new_session,
)
from super_agent.store import store
from tests.fakes.execution import StaticReplyExecutor


def make_session(memory: Memory) -> Session:
    """A session that keeps no records but does hold a memory."""
    engine = new_engine_with_executor(
        StaticReplyExecutor(),
        [Message(role=ROLE_SYSTEM, content="rules"), Message(role=ROLE_USER, content="hello")],
    )
    return new_session(engine, memory=memory)


def test_the_default_backend_keeps_the_memory_beside_the_sessions(tmp_path: Path) -> None:
    """The default is the store the sessions already live in."""
    memory = openMemory(MemorySettings(), store.new(str(tmp_path / "store")))

    assert memory.name == "store"
    assert memory.enabled is True
    memory.save(["a line"])
    assert memory.load() == ["a line"]


def test_the_settings_can_switch_the_memory_off(tmp_path: Path) -> None:
    """The switch is read at startup, so a memory turned off stays off."""
    memory = openMemory(MemorySettings(enabled=False), store.new(str(tmp_path / "store")))

    assert memory.enabled is False
    assert memory.load() == []
    with pytest.raises(MemoryDisabled):
        memory.save(["a line"])


def test_the_file_backend_keeps_the_memory_where_the_user_says(tmp_path: Path) -> None:
    """A second backend is the point of the port: the same memory, elsewhere."""
    path = tmp_path / "shared" / "memory.json"
    memory = openMemory(MemorySettings(backend="file", path=str(path)), None)

    memory.save(["a line"])

    assert memory.name == "file"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == ["a line"]


def test_the_file_backend_needs_a_path() -> None:
    """A backend that cannot say where it writes is a startup failure."""
    with pytest.raises(ValueError, match="needs a path"):
        openMemory(MemorySettings(backend="file"), None)


def test_an_unknown_backend_is_a_startup_failure(tmp_path: Path) -> None:
    """Silently keeping the memory somewhere else is worse than not keeping it."""
    with pytest.raises(ValueError, match="unknown memory backend"):
        openMemory(MemorySettings(backend="elsewhere"), store.new(str(tmp_path / "store")))


def test_the_switch_is_written_into_the_settings_file(tmp_path: Path) -> None:
    """A switch that forgets itself when the process ends is a trap."""
    path = tmp_path / "settings.json"
    save_settings_file(str(path), load_settings_file(str(path)))

    setMemoryEnabled(False, str(path))

    settings = load_settings_file(str(path))
    assert settings.memory.enabled is False
    # The rest of the file is untouched: the memory is one block among many.
    assert settings.provider == load_settings_file(str(path)).provider


@pytest.mark.asyncio
async def test_the_controller_switches_the_memory_and_rebuilds_the_context(tmp_path: Path) -> None:
    """Turning the memory off takes effect at once, not at the next restart."""
    settings = tmp_path / "settings.json"
    save_settings_file(str(settings), load_settings_file(str(settings)))
    memory = openMemory(MemorySettings(), store.new(str(tmp_path / "store")))
    memory.save(["a line"])
    session = make_session(memory)
    controller = MemoryController(memory, session, str(settings))

    await controller.setEnabled(False)

    assert controller.enabled is False
    assert load_settings_file(str(settings)).memory.enabled is False
    assert all(not message.content.startswith(MEMORY_SYSTEM_PREFIX) for message in session.snapshot().messages)


@pytest.mark.asyncio
async def test_the_controller_keeps_the_lines_when_the_memory_comes_back(tmp_path: Path) -> None:
    """Switching off stops the memory being used, not the memory being kept."""
    settings = tmp_path / "settings.json"
    save_settings_file(str(settings), load_settings_file(str(settings)))
    memory = openMemory(MemorySettings(), store.new(str(tmp_path / "store")))
    memory.save(["a line"])
    session = make_session(memory)
    controller = MemoryController(memory, session, str(settings))

    await controller.setEnabled(False)
    await controller.setEnabled(True)

    assert controller.enabled is True
    assert memory.load() == ["a line"]
    assert "a line" in session.snapshot().messages[0].content


def test_the_switch_is_the_same_whatever_is_behind_it(tmp_path: Path) -> None:
    """The switch is an object, not a setting the backends each understand."""
    store_memory = openMemory(MemorySettings(), store.new(str(tmp_path / "store")))
    file_memory = openMemory(MemorySettings(backend="file", path=str(tmp_path / "m.json")), None)

    assert isinstance(store_memory, Switch)
    assert isinstance(file_memory, Switch)
    assert store_memory.name != file_memory.name
