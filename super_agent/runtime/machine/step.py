"""The step marker carried by the runtime data.

A step is one logical model call plus the whole tool batch that call produced.
It exists only while a turn is running, so the marker is a number and nothing
else: the turn boundary is what resets it. The boundary timings are specified in
``docs/spec/runtime.md``.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class Step:
    """The current step of a running turn, numbered from one."""

    index: int = 1
