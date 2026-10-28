"""The driving-side ports: what a front end may ask of the application.

They are narrow on purpose, one per use case. A terminal, a browser tab, and an
editor all read the same snapshot, start the same turn, and send the same three
answers to an approval; nothing else is shared, and no front end is given the
runtime's scheduler.

Implementation lives at the composition boundary
(:mod:`super_agent.app.conversation_adapter`). Type conversion between runtime
values and these DTOs happens there and nowhere else.
"""

from __future__ import annotations

import dataclasses
from typing import Final, Protocol

from super_agent.frontend.approval import Decision
from super_agent.frontend.failure import Failure
from super_agent.frontend.notifications import ConversationNotification
from super_agent.frontend.transport import Cancellation, Channel
from super_agent.frontend.view import ApprovalReceipt, ConversationView, QueuedReceipt, SteeringReceipt

__all__ = [
    "AgentPort",
    "AgentSummary",
    "AttachmentSummary",
    "AttachmentsPort",
    "ConfigPort",
    "ConfigView",
    "Conversation",
    "ExtensionPort",
    "MCPPort",
    "MemoryPort",
    "PermissionPort",
    "ProviderPort",
    "ProviderView",
    "SessionPort",
    "SessionSummary",
    "SnapshotPort",
    "TurnPort",
    "WorkspacePort",
]


@dataclasses.dataclass(frozen=True, slots=True)
class AttachmentSummary:
    """A file queued for the next turn, or carried by a message."""

    name: str = ""
    mime: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class SessionSummary:
    """One saved session, for listing and resuming."""

    id: str = ""
    title: str = ""
    provider: str = ""
    model: str = ""
    cwd: str = ""
    parent_id: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class AgentSummary:
    """One agent profile."""

    name: str = ""
    provider: str = ""
    model: str = ""
    permission_mode: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class MCPServerSummary:
    """One configured MCP server and the tools it discovered.

    A display value rather than a capability: the terminal manages servers, while
    a browser or an editor may only list them.
    """

    name: str = ""
    tools: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class ConfigView:
    """What the application says about itself, for a status bar or a picker.

    Identity first (which session, which workspace), then everything that changes
    behaviour (agent, model, policy), then what this interface may offer. Every
    field is read back from the application, so a display cannot describe a policy
    the runtime is not using.

    An empty field means "not provided" and never "default". ``reasoning_effort``
    is empty today because the application exposes no such setting, and the honest
    rendering is to hide the control rather than invent a level.
    """

    session_id: str = ""
    session_title: str = ""
    #: The directory tools run in, and the roots the workspace allows.
    workspace: str = ""
    roots: tuple[str, ...] = ()
    #: Instruction files loaded into the context, in load order.
    instruction_sources: tuple[str, ...] = ()
    agent: str = ""
    provider: str = ""
    model: str = ""
    permission_mode: str = ""
    auto_approve: bool = False
    reasoning_effort: str = ""
    #: The levels that could be chosen. Empty means the application offers none.
    reasoning_efforts: tuple[str, ...] = ()
    agents: tuple[AgentSummary, ...] = ()
    #: Whether the cross-session memory is in use, and which backend holds it.
    #: The backend is named so an interface can say where the lines live; an
    #: empty name means the application has no memory at all.
    memory_enabled: bool = False
    memory_backend: str = ""
    #: Whether the selected provider has no usable credential yet. True means the
    #: application started without a key, so an interface should offer to enter
    #: one; the first turn fails with the provider's own authentication error.
    credential_missing: bool = False
    #: Whether the strict sandbox was downgraded to ``off`` on this platform.
    #: True means commands run with the operator's full authority, which the
    #: interface should make visible.
    sandbox_downgraded: bool = False
    #: The operations this application performs, so a front end can offer exactly
    #: those. A name absent here is unavailable, not hidden: a browser must not
    #: show a button whose call would fail.
    capabilities: tuple[str, ...] = ()


#: The capability names this contract defines. Each is one operation a front end
#: may offer; the application decides which subset it actually enables.
CAPABILITIES: Final[tuple[str, ...]] = (
    "turn",
    "steer",
    "queue",
    "approve",
    "cancel",
    "resume",
    "rename",
    "delete",
    "compact",
    "undo",
    "fork",
    "export",
    "agents",
    "mcp",
    "memory",
)


class SnapshotPort(Protocol):
    """One read of conversation state."""

    def snapshot(self) -> ConversationView: ...


class ConfigPort(Protocol):
    """One read of the application's identity, policy and capabilities."""

    def config_view(self) -> ConfigView: ...


class TurnPort(Protocol):
    """Running, steering, approving and cancelling the turn in flight."""

    async def run_turn(
        self,
        text: str,
        notifications: Channel[ConversationNotification],
        cancellation: Cancellation,
    ) -> Failure | None:
        """Run one submission, reporting as it goes. Returns the failure, if any.

        The submission is not always one turn: an input queued while this one runs
        belongs to the next turn, and the application starts that turn itself. The
        channel therefore spans the whole submission and is closed when the last
        turn ends.
        """
        ...

    async def steer(self, text: str) -> SteeringReceipt:
        """Submit an input to the running turn's next step.

        Returns immediately, because acceptance is later: the input is held until
        the current step finishes. A rejected receipt means the input joined
        nothing, and its reason is fit to show.
        """
        ...

    async def queue(self, text: str) -> QueuedReceipt:
        """Submit an input for the turn after the running one.

        Returns immediately, because the turn it becomes has not started yet: the
        application holds the input and starts that turn when the current one ends.
        A rejection means no turn was running, so there was nothing for the input
        to follow — the caller should submit it as a turn of its own instead.
        """
        ...

    async def approve(self, decision: Decision, request_id: str = "") -> ApprovalReceipt:
        """Answer the approval ``request_id`` names.

        The id comes from the :class:`~super_agent.frontend.notifications.ToolApprovalRequested`
        the front end displayed, or from ``ConversationView.pending_approval_id``
        when it rebuilt from a snapshot. An answer that does not match a request
        still pending is refused by value, never applied: a decision must not reach
        a tool call the user did not see.
        """
        ...

    async def cancel(self) -> Failure | None:
        """Cancel the turn the runtime is holding, if any."""
        ...


class SessionPort(Protocol):
    """The conversation lifecycle commands operate on."""

    async def reset(self) -> None: ...

    async def list_sessions(self) -> list[SessionSummary]: ...

    async def resume(self, session_id: str) -> None: ...

    async def rename_session(self, session_id: str, title: str) -> None: ...

    async def delete_session(self, session_id: str) -> None: ...

    async def compact(self, summary: str) -> None: ...

    async def undo(self) -> None: ...

    async def fork(self, title: str) -> str: ...

    async def export(self, format: str) -> str: ...


class PermissionPort(Protocol):
    """Reads and changes the active permission policy.

    Mode and approval are read back from the runtime, so a display cannot drift
    from the behaviour it describes.
    """

    async def set_permission_mode(self, mode: str) -> None: ...

    def permission_mode(self) -> str: ...

    def auto_approve_tools(self) -> bool: ...


class AgentPort(Protocol):
    """Lists and selects agent profiles."""

    def list_agents(self) -> list[AgentSummary]: ...

    def current_agent(self) -> AgentSummary: ...

    async def use_agent(self, name: str) -> None: ...


class MemoryPort(Protocol):
    """Reads and writes the cross-session memory, and switches it on or off.

    The memory outlives the conversation, so it is a separate thing from the
    session: switching it off leaves the stored lines where they are, and
    switching it on brings them back.
    """

    async def memories(self) -> list[str]: ...

    async def remember(self, text: str) -> None: ...

    async def forget_memories(self) -> None: ...

    def memory_enabled(self) -> bool: ...

    def memory_backend(self) -> str: ...

    async def set_memory_enabled(self, enabled: bool) -> None: ...


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderView:
    """What a provider is configured as, credential redacted.

    ``api_key`` is never the stored secret: it is either empty (unset) or a
    placeholder meaning "a key is present", so an interface can show state
    without ever displaying the credential itself.
    """

    name: str = ""
    model: str = ""
    base_url: str = ""
    has_key: bool = False


class ProviderPort(Protocol):
    """Reads provider configuration and sets the credential and model.

    Setting a key persists it to ``settings.json`` and rebuilds the active model,
    so the next turn uses it without a restart.
    """

    def list_providers(self) -> list[ProviderView]: ...

    def provider(self, name: str) -> ProviderView: ...

    async def configure_provider(self, name: str, api_key: str, model: str = "") -> None: ...


class MCPPort(Protocol):
    """Manages MCP server lifecycle."""

    def list_mcp_servers(self) -> list[MCPServerSummary]: ...

    async def add_mcp_server(self, name: str, command: str, args: list[str]) -> None: ...

    async def remove_mcp_server(self, name: str) -> None: ...

    async def restart_mcp_server(self, name: str) -> None: ...


class WorkspacePort(Protocol):
    """Runs read-only repository and language-server queries."""

    async def git_diff(self) -> str: ...

    async def git_status(self) -> str: ...

    async def diagnostics(self, path: str) -> str: ...


class ExtensionPort(Protocol):
    """Exposes discovered commands, skills, and plugins."""

    def custom_commands(self) -> list[str]: ...

    async def expand_custom_command(self, name: str, arguments: str) -> str: ...

    def skills(self) -> list[str]: ...

    def plugins(self) -> list[str]: ...


class AttachmentsPort(Protocol):
    """Stages workspace files for the next turn."""

    async def attach(self, path: str) -> AttachmentSummary: ...

    async def pending_attachments(self) -> tuple[AttachmentSummary, ...]: ...


class Conversation(
    SnapshotPort,
    ConfigPort,
    TurnPort,
    SessionPort,
    PermissionPort,
    AgentPort,
    MemoryPort,
    ProviderPort,
    MCPPort,
    WorkspacePort,
    ExtensionPort,
    AttachmentsPort,
    Protocol,
):
    """The bundle a front end needs.

    Both front ends use this contract: the terminal renders it in process, the
    Web transport carries it over HTTP and server-sent events. A capability in
    this bundle is available to both; there is no second, narrower bundle.
    """
