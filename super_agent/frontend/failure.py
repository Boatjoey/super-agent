"""Why an operation did not finish, in words a front end can show.

A front end has to answer two questions about a failure: what to display, and
whether the operation it submitted was ever accepted. Both are facts the
application knows and a renderer does not, so they travel here as a value instead
of as an exception: an interface that has to inspect an exception's type to decide
whether its input was accepted is one refactor away from guessing.

``code`` carries the second answer. ``refused`` means nothing was accepted, so
there is nothing to undo or wait for; ``failed`` and ``cancelled`` mean the work
*was* accepted and then did not finish.
"""

from __future__ import annotations

import dataclasses
from typing import Final

__all__ = ["CANCELLED", "FAILED", "REFUSED", "Failure", "failure_from"]

#: Accepted, then stopped by a cancellation the caller asked for.
CANCELLED: Final[str] = "cancelled"
#: Accepted, then failed.
FAILED: Final[str] = "failed"
#: Not accepted at all: nothing was started, recorded, or promised.
REFUSED: Final[str] = "refused"


@dataclasses.dataclass(frozen=True, slots=True)
class Failure:
    """One failed operation, as a front end reports it.

    ``message`` is fit to show as-is. ``operation`` names the call that failed
    (``run_turn``, ``approve``, ``steer``, …) so a front end can tell which of the
    things it submitted this belongs to. ``request_id`` carries the approval or
    input the failure is about, and is empty when the failure belongs to no single
    request.
    """

    message: str = ""
    code: str = FAILED
    operation: str = ""
    request_id: str = ""


def failure_from(
    error: BaseException | None,
    *,
    operation: str = "",
    request_id: str = "",
    cancelled: bool = False,
) -> Failure | None:
    """A failure value for ``error``, or ``None`` when there was no error.

    An error with no message still has a type, and an empty message would read as
    "nothing happened". ``cancelled`` is passed in rather than sniffed from the
    type: only the caller knows whether this exception means cancellation.
    """
    if error is None:
        return None
    message = str(error) or type(error).__name__
    return Failure(
        message=message,
        code=CANCELLED if cancelled else FAILED,
        operation=operation,
        request_id=request_id,
    )
