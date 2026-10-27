"""An input the user submitted while a turn was already running.

Steering belongs to the current turn rather than to the next one, so the machine
holds it in run data until the next step begins and only then appends it to the
conversation. Holding it as a value keeps the queue of accepted-but-not-yet
consumed inputs visible, which is what makes the acceptance point explicit.
"""

from __future__ import annotations

import dataclasses

from super_agent.runtime.protocol.types import Attachment


@dataclasses.dataclass(frozen=True, slots=True)
class SteeringInput:
    """One in-turn input waiting for the next step.

    ``id`` is the submitter's correlation id, echoed back when the input is
    accepted or discarded. It is opaque to the machine: the runtime never
    interprets it, it only carries it so the submission and its receipt can be
    matched. An input without one cannot be announced, so only its effect on the
    conversation remains visible.
    """

    id: str = ""
    content: str = ""
    attachments: tuple[Attachment, ...] = ()
