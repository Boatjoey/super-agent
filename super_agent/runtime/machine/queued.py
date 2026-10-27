"""An input the user queued for the turn after the running one.

Queued input belongs to the next turn rather than to the current one, so the
machine holds it in run data *across* the turn boundary: the turn that was
running when it arrived never sees it. Holding it as a value keeps the queue of
accepted-but-not-yet-started inputs visible, which is what makes the acceptance
point — the start of the next turn — something the machine can report.
"""

from __future__ import annotations

import dataclasses

from super_agent.runtime.protocol.types import Attachment


@dataclasses.dataclass(frozen=True, slots=True)
class QueuedInput:
    """One input waiting for the next turn.

    ``id`` is the submitter's correlation id, echoed back when the input is taken
    up as a turn or discarded with the turn it was waiting behind. It is opaque to
    the machine: the runtime never interprets it, it only carries it so the
    submission and its receipt can be matched. An input without one cannot be
    announced, so only its effect on the conversation remains visible.
    """

    id: str = ""
    content: str = ""
    attachments: tuple[Attachment, ...] = ()
