"""The static files the web interface is made of.

They ship inside the package rather than beside the repository root, so an
installed wheel serves the same interface a checkout does. Only these names are
ever read: a request path is a lookup in a fixed table, never a filesystem path,
so ``..`` cannot escape anything.
"""

from __future__ import annotations

import importlib.resources
from importlib.resources.abc import Traversable

__all__ = ["CONTENT_TYPES", "Assets"]

#: The extension a browser needs to render each file we ship.
CONTENT_TYPES: dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}

#: The index for a bare path. One page, so there is nothing to negotiate.
INDEX = "index.html"


class Assets:
    """Read-only access to the packaged interface files."""

    __slots__ = ("_root",)

    def __init__(self, root: Traversable | None = None) -> None:
        self._root = root if root is not None else importlib.resources.files("super_agent.web") / "static"

    def read(self, name: str) -> tuple[bytes, str] | None:
        """The file and its content type, or ``None`` when there is no such file.

        ``name`` is a plain file name; a path separator, a leading dot, or an
        unknown extension is a miss rather than a probe.
        """
        if name in ("", "/"):
            name = INDEX
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        suffix = name[name.rfind(".") :] if "." in name else ""
        content_type = CONTENT_TYPES.get(suffix)
        if content_type is None:
            return None
        target = self._root / name
        if not target.is_file():
            return None
        return target.read_bytes(), content_type
