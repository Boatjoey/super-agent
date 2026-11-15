"""History use cases: listing, forking, memory, resume, compaction, and undo.

Every one of these rewrites the conversation, so every one of them takes the turn
lock and refuses to run while a turn is in flight. Where a write could fail, it
happens before the in-memory change so a failure leaves one consistent side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import ROLE_SYSTEM, ROLE_TOOL, Message
from super_agent.runtime.session.memory import Memory, MemoryDisabledError, with_memory_context
from super_agent.runtime.session.repository import (
    WORKSPACE_ACCESS_READ_WRITE,
    Metadata,
    Repository,
    SessionID,
    Summary,
    WorkspaceRootSpec,
    WorkspaceSpec,
    workspace_spec_pointer,
)

if TYPE_CHECKING:
    from super_agent.runtime.engine import Engine, EngineView
    from super_agent.runtime.session.repository import Workspace
    from super_agent.runtime.session.snapshot_emitter import SnapshotEmitter


class HistoryMixin:
    """Conversation history use cases."""

    if TYPE_CHECKING:
        engine: Engine
        emitter: SnapshotEmitter
        repository: Repository | None
        workspace: Workspace | None
        meta: Metadata
        memory: Memory

        def _try_lock(self) -> bool: ...
        def _unlock(self) -> None: ...
        def meta_id(self) -> SessionID: ...
        def metadata(self) -> Metadata: ...
        def snapshot(self) -> EngineView: ...

    # --- listing and forking -------------------------------------------------

    def list_sessions(self) -> list[Summary]:
        if self.repository is None:
            raise ValueError("session store is not configured")
        return self.repository.list()

    async def fork(self, title: str) -> Metadata:
        """Copy this session's conversation into a new stored session."""
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            if self.repository is None:
                raise ValueError("session store is not configured")
            current = self.metadata()
            title = title.strip()
            if title == "":
                title = current.title + " (fork)"
            messages = list(self.snapshot().messages)
            created = self.repository.create(
                Metadata(
                    title=title,
                    provider=current.provider,
                    model=current.model,
                    cwd=current.cwd,
                    instruction_sources=current.instruction_sources,
                    parent_id=current.id,
                    project_id=current.project_id,
                    config_root=current.config_root,
                    workspace_spec=_spec_from_workspace(self.workspace),
                ),
                messages,
            )
            await self.engine.replace_messages(messages)
            self.meta = created
            self._rearm_emitter(len(messages))
            return created
        finally:
            self._unlock()

    # --- memory --------------------------------------------------------------

    def memories(self) -> list[str]:
        """The stored lines, empty when the memory is off or has none."""
        return self.memory.load()

    async def remember(self, value: str) -> None:
        """Add one line to the cross-session memory, if it is not already there."""
        value = value.strip()
        if value == "":
            raise ValueError("memory text is required")
        if not self.memory.enabled:
            raise MemoryDisabledError("cross-session memory is off")
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            items = self.memory.load()
            if value in items:
                return
            items.append(value)
            self.memory.save(items)
            await self._replace_memory_context(items)
        finally:
            self._unlock()

    async def forget_memories(self) -> None:
        """Drop every stored line, leaving the memory itself in place."""
        if not self.memory.enabled:
            raise MemoryDisabledError("cross-session memory is off")
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            self.memory.save([])
            await self._replace_memory_context([])
        finally:
            self._unlock()

    async def refresh_memory(self) -> None:
        """Rebuild the memory context from the port, adding or removing it.

        This is what makes the switch take effect at once: the conversation
        either carries the memory lines or does not, and the transcript on disk
        agrees with it.
        """
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            await self._replace_memory_context(self.memory.load())
        finally:
            self._unlock()

    async def _replace_memory_context(self, items: list[str]) -> None:
        kept = with_memory_context(list(self.snapshot().messages), items)
        if self.repository is not None:
            self.repository.save_conversation_replacement(self.meta_id(), kept)
        await self.engine.replace_messages(kept)
        self.emitter.reset(len(kept))

    # --- resume --------------------------------------------------------------

    async def resume(self, session_id: SessionID) -> None:
        """Restore a stored session, upgrading legacy metadata exactly once.

        Every validation happens before anything is activated, so a resume that
        cannot succeed leaves the current session untouched. The resume never
        falls back to the process working directory: a saved workspace that no
        longer validates is a hard failure.
        """
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            if self.repository is None:
                raise ValueError("session store is not configured")
            messages, meta = self.repository.load(session_id)
            if self.workspace is None:
                raise ValueError("workspace is not configured")
            spec, legacy = saved_workspace_spec(meta)
            if legacy:
                # Sessions written before WorkspaceSpec saved only a cwd and
                # never promised it was canonical, so upgrade it once:
                # re-resolve the saved cwd against the current filesystem and
                # persist the result. Every later resume takes the strict path.
                try:
                    spec = self.workspace.canonicalize(spec)
                except Exception as error:
                    raise ValueError(f"saved workspace is no longer valid: {error}") from error
            try:
                self.workspace.validate(spec)
            except Exception as error:
                raise ValueError(f"saved workspace is no longer valid: {error}") from error
            if legacy:
                # Persist before mutating the active session so a failed write
                # leaves the resume untouched instead of half applied.
                try:
                    self.repository.save_workspace_description(session_id, spec)
                except Exception as error:
                    raise ValueError(f"persist migrated workspace: {error}") from error
            memories = self.memory.load()
            messages = with_memory_context(messages, memories)
            self.repository.save_conversation_replacement(session_id, messages)
            try:
                self.workspace.activate(spec)
            except Exception as error:
                raise ValueError(f"saved workspace is no longer valid: {error}") from error

            meta = _with_workspace(meta, spec)
            await self.engine.replace_messages(messages)
            self.meta = meta
            self._rearm_emitter(len(messages))
        finally:
            self._unlock()

    def rename_session(self, session_id: SessionID, title: str) -> None:
        if self.repository is None:
            raise ValueError("session store is not configured")
        self.repository.rename_session(session_id, title)

    def delete_session(self, session_id: SessionID) -> None:
        if self.repository is None:
            raise ValueError("session store is not configured")
        if session_id == self.meta_id():
            raise ValueError("cannot delete active session")
        self.repository.delete(session_id)

    # --- compaction and undo -------------------------------------------------

    async def compact(self, ctx: RunContext, summary: str, keep_newest: int) -> None:
        """Replace older turns with a summary, keeping the newest few.

        The compaction record is persisted before the engine is replaced, so the
        in-memory and on-disk transcripts cannot disagree.
        """
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            if self.repository is None:
                raise ValueError("session store is not configured")
            snapshot = self.snapshot()
            if not snapshot.messages:
                return
            if keep_newest < 1:
                keep_newest = 4
            current = list(snapshot.messages)
            if non_system_message_count(current) <= keep_newest:
                return
            summary = summary.strip()
            if summary == "":
                summary = await self.engine.compact_summary(ctx)
            kept = compacted_messages(current, summary, keep_newest)
            original = list(current)
            self.repository.save_compaction(self.meta_id(), summary, original, kept)
            await self.engine.replace_messages(kept)
            # The kept messages were already emitted and persisted through the
            # compaction record; re-emitting them would duplicate the transcript.
            self.emitter.emitted_messages = len(kept)
        finally:
            self._unlock()

    async def undo(self) -> None:
        """Restore the workspace to the last checkpoint and drop what came after.

        The files are restored first. Only when that succeeds is the transcript
        truncated, so a failed restore cannot lose history for good.
        """
        if not self._try_lock():
            raise RuntimeError("session is already running a turn")
        try:
            if self.repository is None:
                raise ValueError("session store is not configured")
            if self.workspace is None:
                raise ValueError("workspace is not configured")
            try:
                files, messages, index = self.repository.load_undo_point(self.meta_id())
            except Exception as error:
                raise ValueError("no checkpoint to undo") from error
            self.workspace.restore(files)
            self.repository.truncate_after(self.meta_id(), index)
            await self.engine.replace_messages(messages)
            self.emitter.emitted_messages = len(messages)
        finally:
            self._unlock()

    def _rearm_emitter(self, emitted: int) -> None:
        from super_agent.runtime.session.snapshot_emitter import SnapshotEmitter

        self.emitter = SnapshotEmitter()
        self.emitter.emitted_messages = emitted


def non_system_message_count(messages: list[Message]) -> int:
    return sum(1 for message in messages if message.role != ROLE_SYSTEM)


def compacted_messages(messages: list[Message], summary: str, keep_newest: int) -> list[Message]:
    """Keep every system message, add the summary, and keep the newest turns.

    When the kept window would start on a ``tool`` message, it is widened
    backwards: a tool result with no preceding tool call is a transcript the
    provider rejects.
    """
    system = [message for message in messages if message.role == ROLE_SYSTEM]
    rest = [message for message in messages if message.role != ROLE_SYSTEM]
    if len(rest) <= keep_newest:
        return [*system, *rest]
    kept = [*system, Message(role=ROLE_SYSTEM, content="Conversation summary:\n" + summary)]
    start = len(rest) - keep_newest
    if rest[start].role == ROLE_TOOL:
        while start > 0 and rest[start].role == ROLE_TOOL:
            start -= 1
    return [*kept, *rest[start:]]


def saved_workspace_spec(meta: Metadata) -> tuple[WorkspaceSpec, bool]:
    """The durable workspace description a resume must restore.

    The second element marks metadata written before ``WorkspaceSpec``: it carries
    only a cwd, which the resume upgrades to a canonical spec exactly once.
    """
    if meta.workspace_spec is not None:
        return workspace_spec_pointer(meta.workspace_spec), False
    if meta.cwd == "":
        raise ValueError("saved workspace is no longer valid: legacy session has no cwd")
    return (
        WorkspaceSpec(
            primary_root=meta.cwd,
            cwd=meta.cwd,
            roots=(WorkspaceRootSpec(path=meta.cwd, access=WORKSPACE_ACCESS_READ_WRITE),),
        ),
        True,
    )


def _spec_from_workspace(workspace: Workspace | None) -> WorkspaceSpec | None:
    if workspace is None:
        return None
    return workspace_spec_pointer(workspace.spec())


def _with_workspace(meta: Metadata, spec: WorkspaceSpec) -> Metadata:
    return Metadata(
        id=meta.id,
        title=meta.title,
        provider=meta.provider,
        model=meta.model,
        cwd=spec.cwd,
        instruction_sources=meta.instruction_sources,
        parent_id=meta.parent_id,
        project_id=meta.project_id,
        config_root=meta.config_root,
        workspace_spec=workspace_spec_pointer(spec),
    )
