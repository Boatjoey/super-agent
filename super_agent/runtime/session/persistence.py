"""Message durability progress and audit writes, independent of notification delivery."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from super_agent.runtime.machine import ApprovalDecision, Message, ToolCall

if TYPE_CHECKING:
    from super_agent.runtime.session.repository import Repository, SessionID


class MessagePersistence:
    """Track acknowledged appends; reconcile uncertain writes before retrying."""

    def __init__(self, session_id: SessionID, initial: Sequence[Message] = ()) -> None:
        self._session_id = session_id
        self._messages = list(initial)
        self._reconcile = False

    @property
    def persisted_count(self) -> int:
        return len(self._messages)

    def persist_new_messages(
        self, repository: Repository | None, session_id: SessionID, messages: Sequence[Message]
    ) -> None:
        if repository is None:
            self._session_id = session_id
            self._messages = list(messages)
            return
        if session_id != self._session_id or list(messages[: self.persisted_count]) != self._messages:
            self._reconcile = True
        if self._reconcile:
            durable, _meta = repository.load(session_id)
            if list(messages[: len(durable)]) != durable:
                raise ValueError("stored message history does not match the committed snapshot")
            self._messages = list(durable)
            self._session_id = session_id
            self._reconcile = False
        for message in messages[self.persisted_count :]:
            try:
                repository.save_message(session_id, message)
            except Exception:
                self._reconcile = True
                raise
            self._messages.append(message)


class PersistenceMixin:
    """Write-through helpers for the stored transcript."""

    if TYPE_CHECKING:
        repository: Repository | None

        def metaID(self) -> SessionID: ...

    def persistTurnBoundary(self) -> None:
        """Start a new turn id, so a resumed transcript can be grouped by turn."""
        if self.repository is not None:
            self.repository.assign_new_turn_id(self.metaID())

    def persistMessage(self, message: Message) -> None:
        if self.repository is not None:
            self.repository.save_message(self.metaID(), message)

    def persistApproval(self, decision: ApprovalDecision, call: ToolCall) -> None:
        """Approval decisions are audited and never sent to a model."""
        if self.repository is None:
            return
        self.repository.save_approval(self.metaID(), decision, call)

    def persistError(self, error: BaseException | None) -> None:
        if self.repository is not None and error is not None:
            self.repository.save_error(self.metaID(), error)
