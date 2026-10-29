"""Process-wide telemetry routing and run correlation, without file I/O."""

from typing import Final

from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.telemetry import Fields as Fields, install as install, record as record


class IDs:
    """The run and action a record belongs to."""

    __slots__ = ("action_id", "run_id")

    def __init__(self, run_id: str = "", action_id: str = "") -> None:
        self.run_id = run_id
        self.action_id = action_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IDs):
            return NotImplemented
        return self.run_id == other.run_id and self.action_id == other.action_id

    def __repr__(self) -> str:
        return f"IDs(run_id={self.run_id!r}, action_id={self.action_id!r})"


_IDS_KEY: Final[object] = object()


def with_i_ds(ctx: RunContext, run_id: str, action_id: str) -> RunContext:
    """A context derived from ``ctx`` carrying the run and action identity.

    The derived context shares ``ctx``'s cancellation, so waiting on either
    observes the same cancel.
    """
    return ctx.with_value(_IDS_KEY, IDs(run_id=run_id, action_id=action_id))


def i_ds_from(ctx: RunContext) -> IDs:
    """The identity attached to ``ctx``, or an empty one."""
    ids = ctx.value(_IDS_KEY)
    return ids if isinstance(ids, IDs) else IDs()
