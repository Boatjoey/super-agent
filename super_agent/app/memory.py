"""Cross-session memory: choosing where the lines live, and the switch.

The settings name a backend and say whether the memory is in use. This module
turns that into a port: the session store's own file, a file the user names,
or nothing at all. The switch is the same object whichever backend is behind
it, so "turn the memory off" never depends on where the lines are stored.

The switch is also persisted. A switch that forgets itself when the process
ends is a trap: the user turns memory off, restarts, and finds it on again.
"""

from __future__ import annotations

import dataclasses
import os

from super_agent.app.config import (
    MemorySettings,
    load_settings_file,
    save_settings_file,
)
from super_agent.application.memory import MemoryController as ApplicationMemoryController
from super_agent.runtime.session import Session
from super_agent.runtime.session.memory import Memory, Switch
from super_agent.store.memory import FileMemory, StoreMemory
from super_agent.store.store import Store

__all__ = [
    "BACKENDS",
    "BACKEND_FILE",
    "BACKEND_STORE",
    "MemoryController",
    "openMemory",
    "setMemoryEnabled",
]

#: The memory kept beside the sessions, in the session store's own file.
BACKEND_STORE = "store"
#: The memory kept in a file the user names, which may be anywhere.
BACKEND_FILE = "file"
#: Every backend the settings may name.
BACKENDS = (BACKEND_STORE, BACKEND_FILE)


def openMemory(settings: MemorySettings, store: Store | None) -> Switch:
    """The backend the settings name, behind the switch they set.

    An unknown backend is a startup failure rather than a silent fallback: a
    memory that quietly lands somewhere else is worse than one that does not
    exist.
    """
    backend = settings.backend or BACKEND_STORE
    if backend == BACKEND_STORE:
        if store is None:
            raise ValueError("the store memory backend needs a session store")
        inner: Memory = StoreMemory(store)
    elif backend == BACKEND_FILE:
        if settings.path == "":
            raise ValueError("the file memory backend needs a path")
        inner = FileMemory(os.path.expanduser(settings.path))
    else:
        raise ValueError("unknown memory backend: " + backend)
    return Switch(inner, enabled=settings.enabled)


def setMemoryEnabled(enabled: bool, path: str) -> None:
    """Write the switch into ``settings.json``, leaving the rest of the file alone."""
    settings = load_settings_file(path)
    memory = dataclasses.replace(settings.memory, enabled=enabled)
    save_settings_file(path, dataclasses.replace(settings, memory=memory))


class MemoryPreferencesAdapter:
    def __init__(self, path: str) -> None:
        self.path = path

    def set_enabled(self, enabled: bool) -> None:
        setMemoryEnabled(enabled, self.path)


class MemoryController(ApplicationMemoryController):
    """Compatibility constructor that injects settings persistence."""

    def __init__(self, switch: Switch, session: Session | None = None, path: str = "") -> None:
        super().__init__(switch, session, MemoryPreferencesAdapter(path) if path else None)
