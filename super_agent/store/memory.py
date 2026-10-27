"""Cross-session memory backends that keep their lines in files.

Two backends, one port: the session store's own file, and a file the user
names. The second is what makes the abstraction worth having — a memory shared
through a synced folder is a different product decision from the one that lives
next to the sessions, and the runtime must not care which.

Both files hold the same thing: a JSON array of strings, written atomically with
mode ``0600``, because a memory is the user's own words about themselves.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from typing import Any, cast

from super_agent import jsonutil
from super_agent.store.store import Store

__all__ = ["FileMemory", "StoreMemory"]


class StoreMemory:
    """Memory kept in the session store's own file."""

    __slots__ = ("_store",)

    def __init__(self, store: Store) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "store"

    @property
    def enabled(self) -> bool:
        return True

    def load(self) -> list[str]:
        return self._store.load_memory()

    def save(self, items: Sequence[str]) -> None:
        self._store.save_memory(items)


class FileMemory:
    """Memory kept in a JSON array at a path the user names."""

    __slots__ = ("_path",)

    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def name(self) -> str:
        return "file"

    @property
    def enabled(self) -> bool:
        return True

    def load(self) -> list[str]:
        try:
            with open(self._path, encoding="utf-8") as handle:
                content = handle.read()
        except FileNotFoundError:
            return []
        data: Any = json.loads(content)
        if not isinstance(data, list):
            raise TypeError(f"memory must be a JSON array, got {type(data).__name__}")
        return [str(item) for item in cast("list[Any]", data)]

    def save(self, items: Sequence[str]) -> None:
        """Replace the file's contents atomically, so a crash cannot truncate it."""
        content = (jsonutil.dumps(list(items), indent=2) + "\n").encode("utf-8")
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, mode=0o700, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".memory-", suffix=".json")
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            # The rename is the only step that removes the temp file; anything
            # else leaves it behind, and a failed remove must not mask the real
            # failure.
            with contextlib.suppress(OSError):
                os.remove(temporary)
            raise
