"""The three answers a tool approval can receive.

The values are spelled as the runtime spells them; a front end that offers two
buttons instead of three simply never sends ``always``.
"""

from __future__ import annotations

from typing import Final

__all__ = ["APPROVE_ALWAYS", "APPROVE_ONCE", "DENY", "Decision"]


class Decision(str):
    """The answer the runtime receives for one tool call."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"Decision({str.__repr__(self)})"


APPROVE_ONCE: Final[Decision] = Decision("once")
APPROVE_ALWAYS: Final[Decision] = Decision("always")
DENY: Final[Decision] = Decision("deny")
