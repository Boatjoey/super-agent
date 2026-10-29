"""Interaction-port doubles shared by interactive CLI tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from super_agent.tui import (
    CAPABILITIES,
    ROLE_ASSISTANT,
    AgentStatus,
    AgentSummary,
    App,
    ApprovalReceipt,
    AttachmentSummary,
    Cancellation,
    Channel,
    ConfigView,
    ConversationNotification,
    ConversationView,
    Decision,
    Failure,
    MCPServerSummary,
    Message,
    MessageAppended,
    Option,
    PermissionRequest,
    ProviderView,
    QueuedReceipt,
    SessionSummary,
    StartupInfo,
    SteeringReceipt,
    ToolApprovalCleared,
    ToolApprovalRequested,
    ToolCall,
    new,
)


class FakeFrontendPorts:
    """A conversation port with scripted notifications and submission receipts."""

    def __init__(
        self,
        script: Sequence[ConversationNotification] = (),
        receipts: Sequence[SteeringReceipt] = (),
        queued: Sequence[QueuedReceipt] = (),
    ) -> None:
        self.script = list(script)
        self.receipts = list(receipts)
        self.queuedReceipts = list(queued)
        self.queries: list[str] = []
        self.steers: list[str] = []
        self.queued: list[str] = []
        self.approvals: list[tuple[str, Decision]] = []
        self.cancellations = 0
        self.current_permission_mode = ""
        self.memory_items: list[str] = []
        self.memory_on = True
        self.memory_switches: list[bool] = []
        self.providers: list[ProviderView] = []
        self.configured: list[tuple[str, str, str]] = []

    def snapshot(self) -> ConversationView:
        return ConversationView(agent_status=AgentStatus(label="Idle"))

    def config_view(self) -> ConfigView:
        return ConfigView(
            permission_mode=self.current_permission_mode,
            memory_enabled=self.memory_on,
            memory_backend="store",
            capabilities=CAPABILITIES,
        )

    async def run_turn(
        self,
        text: str,
        notifications: Channel[ConversationNotification],
        cancellation: Cancellation,
    ) -> Failure | None:
        self.queries.append(text)
        for notification in self.script:
            notifications.put(notification)
        notifications.close()
        return None

    async def approve(self, decision: Decision, request_id: str = "") -> ApprovalReceipt:
        """Refuse by default: nothing here is waiting on an approval."""
        self.approvals.append((request_id, decision))
        return ApprovalReceipt.rejected(request_id, "no tool call is waiting for a decision")

    async def steer(self, text: str) -> SteeringReceipt:
        """Hold the input, unless the test scripted a refusal."""
        self.steers.append(text)
        if self.receipts:
            return self.receipts.pop(0)
        return SteeringReceipt.held(f"steer-{len(self.steers)}")

    async def queue(self, text: str) -> QueuedReceipt:
        """Accept the input for the next turn, unless the test scripted a refusal."""
        self.queued.append(text)
        if self.queuedReceipts:
            return self.queuedReceipts.pop(0)
        return QueuedReceipt.queued(f"queue-{len(self.queued)}")

    async def cancel(self) -> Failure | None:
        self.cancellations += 1
        return None

    async def reset(self) -> None:
        return None

    async def list_sessions(self) -> list[SessionSummary]:
        return []

    async def resume(self, session_id: str) -> None:
        return None

    async def rename_session(self, session_id: str, title: str) -> None:
        return None

    async def delete_session(self, session_id: str) -> None:
        return None

    async def compact(self, summary: str) -> None:
        return None

    async def undo(self) -> None:
        return None

    async def fork(self, title: str) -> str:
        return "fork"

    async def export(self, format: str) -> str:
        return "/tmp/export"

    async def set_permission_mode(self, mode: str) -> None:
        self.current_permission_mode = mode

    def permission_mode(self) -> str:
        return self.current_permission_mode

    def auto_approve_tools(self) -> bool:
        return self.current_permission_mode == "bypass"

    def list_mcp_servers(self) -> list[MCPServerSummary]:
        return []

    async def add_mcp_server(self, name: str, command: str, args: list[str]) -> None:
        return None

    async def remove_mcp_server(self, name: str) -> None:
        return None

    async def restart_mcp_server(self, name: str) -> None:
        return None

    def list_agents(self) -> list[AgentSummary]:
        return []

    def current_agent(self) -> AgentSummary:
        return AgentSummary()

    async def use_agent(self, name: str) -> None:
        return None

    def list_providers(self) -> list[ProviderView]:
        return list(self.providers)

    def provider(self, name: str) -> ProviderView:
        for item in self.providers:
            if item.name == name:
                return item
        return ProviderView()

    async def configure_provider(self, name: str, api_key: str, model: str = "") -> None:
        self.configured.append((name, api_key, model))

    async def memories(self) -> list[str]:
        return list(self.memory_items)

    async def remember(self, text: str) -> None:
        self.memory_items.append(text)

    async def forget_memories(self) -> None:
        self.memory_items.clear()

    def memory_enabled(self) -> bool:
        return self.memory_on

    def memory_backend(self) -> str:
        return "store"

    async def set_memory_enabled(self, enabled: bool) -> None:
        self.memory_switches.append(enabled)
        self.memory_on = enabled

    async def git_diff(self) -> str:
        return "diff"

    async def git_status(self) -> str:
        return "status"

    async def diagnostics(self, path: str) -> str:
        return "[]"

    def custom_commands(self) -> list[str]:
        return []

    async def expand_custom_command(self, name: str, arguments: str) -> str:
        raise KeyError(name)

    def skills(self) -> list[str]:
        return []

    def plugins(self) -> list[str]:
        return []

    async def attach(self, path: str) -> AttachmentSummary:
        return AttachmentSummary(name=path, mime="text/plain")

    async def pending_attachments(self) -> tuple[AttachmentSummary, ...]:
        return ()


class ApprovalFrontendPorts(FakeFrontendPorts):
    """A turn that completes after one inline approval.

    It honours the same rule the application does: an answer must name the request
    the turn announced, and only once.
    """

    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[Decision] = []
        self.pending_request_id = "approval-1"
        self._answers: asyncio.Queue[Decision] = asyncio.Queue(maxsize=1)

    async def run_turn(
        self,
        text: str,
        notifications: Channel[ConversationNotification],
        cancellation: Cancellation,
    ) -> Failure | None:
        self.queries.append(text)
        notifications.put(
            ToolApprovalRequested(
                tool_call=ToolCall(name="bash", input="printf ok"),
                request=PermissionRequest(tool_name="bash", command_class="read-only", cwd="/repo", reason="risky"),
                request_id=self.pending_request_id,
                batch_index=1,
                batch_total=1,
            )
        )
        decision = await self._answers.get()
        self.decisions.append(decision)
        notifications.put(ToolApprovalCleared(request_id=self.pending_request_id))
        notifications.put(MessageAppended(message=Message(role=ROLE_ASSISTANT, content="approved")))
        notifications.close()
        return None

    async def approve(self, decision: Decision, request_id: str = "") -> ApprovalReceipt:
        self.approvals.append((request_id, decision))
        if request_id != self.pending_request_id:
            return ApprovalReceipt.rejected(request_id, "that request is no longer pending")
        self.pending_request_id = ""
        await self._answers.put(decision)
        return ApprovalReceipt.accepted(request_id)


def new_app(fake: FakeFrontendPorts, *options: Option) -> App:
    return new(fake, StartupInfo(model_name="test-model"), *options)
