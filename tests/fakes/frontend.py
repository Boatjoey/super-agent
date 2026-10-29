"""A complete frontend contract that needs no runtime.

The web adapter is a transport: it may only depend on
``super_agent.frontend``, so its tests must not build an engine. This double
implements that contract and nothing else, which is also what proves the contract
is small enough for a transport to drive.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from super_agent import frontend


class FakeFrontendPorts:
    """One scripted frontend contract: fixed view, scripted notifications."""

    def __init__(
        self,
        *,
        view: frontend.ConversationView | None = None,
        notifications: Sequence[frontend.ConversationNotification] = (),
        receipts: Sequence[frontend.SteeringReceipt] = (),
        sessions: Sequence[frontend.SessionSummary] = (),
        agents: Sequence[frontend.AgentSummary] = (),
        error: frontend.Failure | None = None,
        mode: str = "ask",
        config: frontend.ConfigView | None = None,
    ) -> None:
        self.view = view if view is not None else frontend.ConversationView()
        self.notifications = list(notifications)
        self.receipts = list(receipts)
        self.sessions = list(sessions)
        self.agents = list(agents)
        self.error = error
        self.mode = mode
        self.config = config
        self.queries: list[str] = []
        self.steers: list[str] = []
        self.queued: list[str] = []
        self.cancellations = 0
        self.resumes: list[str] = []
        self.renames: list[tuple[str, str]] = []
        self.deletions: list[str] = []
        self.resets = 0
        self.undos = 0
        self.modes: list[str] = []
        self.used_agents: list[str] = []
        self.approvals: list[tuple[str, frontend.Decision]] = []
        self.memory_items: list[str] = []
        self.remembered: list[str] = []
        self.memory_switches: list[bool] = []
        self.memory_on = True
        self.providers: list[frontend.ProviderView] = []
        self.configured: list[tuple[str, str, str]] = []
        self.mcp_servers: list[frontend.MCPServerSummary] = []
        self.added_mcp: list[tuple[str, str, list[str]]] = []
        self.removed_mcp: list[str] = []
        self.restarted_mcp: list[str] = []
        self.attachments: list[frontend.AttachmentSummary] = []
        self.expanded_commands: list[tuple[str, str]] = []
        self.last_turn: (
            tuple[
                frontend.Channel[frontend.ConversationNotification],
                frontend.Cancellation,
            ]
            | None
        ) = None

    def snapshot(self) -> frontend.ConversationView:
        return self.view

    def config_view(self) -> frontend.ConfigView:
        if self.config is not None:
            return self.config
        agent = self.current_agent()
        return frontend.ConfigView(
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            permission_mode=self.permission_mode(),
            auto_approve=self.auto_approve_tools(),
            agents=tuple(self.agents),
            memory_enabled=self.memory_on,
            memory_backend="store",
            capabilities=frontend.CAPABILITIES,
        )

    async def run_turn(
        self,
        text: str,
        notifications: frontend.Channel[frontend.ConversationNotification],
        cancellation: frontend.Cancellation,
    ) -> frontend.Failure | None:
        self.queries.append(text)
        self.last_turn = (notifications, cancellation)
        for notification in self.notifications:
            notifications.put(notification)
        notifications.close()
        return self.error

    async def steer(self, text: str) -> frontend.SteeringReceipt:
        self.steers.append(text)
        if self.receipts:
            return self.receipts.pop(0)
        return frontend.SteeringReceipt.held(f"steer-{len(self.steers)}")

    async def queue(self, text: str) -> frontend.QueuedReceipt:
        self.queued.append(text)
        return frontend.QueuedReceipt.queued(f"queue-{len(self.queued)}")

    async def approve(self, decision: frontend.Decision, request_id: str = "") -> frontend.ApprovalReceipt:
        """Refuse by default: nothing here is waiting on an approval."""
        self.approvals.append((request_id, decision))
        return frontend.ApprovalReceipt.rejected(request_id, "no tool call is waiting for a decision")

    async def cancel(self) -> frontend.Failure | None:
        self.cancellations += 1
        return None

    async def reset(self) -> None:
        self.resets += 1

    async def list_sessions(self) -> list[frontend.SessionSummary]:
        return list(self.sessions)

    async def resume(self, session_id: str) -> None:
        self.resumes.append(session_id)

    async def rename_session(self, session_id: str, title: str) -> None:
        self.renames.append((session_id, title))

    async def delete_session(self, session_id: str) -> None:
        self.deletions.append(session_id)

    async def compact(self, summary: str) -> None:
        del summary

    async def undo(self) -> None:
        self.undos += 1

    async def fork(self, title: str) -> str:
        del title
        return "fork-1"

    async def export(self, format: str) -> str:
        del format
        return ""

    async def set_permission_mode(self, mode: str) -> None:
        self.modes.append(mode)
        self.mode = mode

    def permission_mode(self) -> str:
        return self.mode

    def auto_approve_tools(self) -> bool:
        return self.mode == "bypass"

    def list_agents(self) -> list[frontend.AgentSummary]:
        return list(self.agents)

    def current_agent(self) -> frontend.AgentSummary:
        return self.agents[0] if self.agents else frontend.AgentSummary()

    async def use_agent(self, name: str) -> None:
        self.used_agents.append(name)

    # --- provider configuration ----------------------------------------------

    def list_providers(self) -> list[frontend.ProviderView]:
        return list(self.providers)

    def provider(self, name: str) -> frontend.ProviderView:
        for item in self.providers:
            if item.name == name:
                return item
        return frontend.ProviderView()

    async def configure_provider(self, name: str, api_key: str, model: str = "") -> None:
        self.configured.append((name, api_key, model))

    # --- cross-session memory ------------------------------------------------

    async def memories(self) -> list[str]:
        return list(self.memory_items)

    async def remember(self, text: str) -> None:
        self.remembered.append(text)
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

    # --- MCP, workspace queries, extensions, attachments ---------------------

    def list_mcp_servers(self) -> list[frontend.MCPServerSummary]:
        return list(self.mcp_servers)

    async def add_mcp_server(self, name: str, command: str, args: list[str]) -> None:
        self.added_mcp.append((name, command, list(args)))
        self.mcp_servers.append(frontend.MCPServerSummary(name=name))

    async def remove_mcp_server(self, name: str) -> None:
        self.removed_mcp.append(name)
        self.mcp_servers = [item for item in self.mcp_servers if item.name != name]

    async def restart_mcp_server(self, name: str) -> None:
        self.restarted_mcp.append(name)

    async def attach(self, path: str) -> frontend.AttachmentSummary:
        item = frontend.AttachmentSummary(name=path, mime="text/plain")
        self.attachments.append(item)
        return item

    async def pending_attachments(self) -> tuple[frontend.AttachmentSummary, ...]:
        return tuple(self.attachments)

    async def git_diff(self) -> str:
        return "diff"

    async def git_status(self) -> str:
        return "status"

    async def diagnostics(self, path: str) -> str:
        return f"diagnostics:{path}"

    def custom_commands(self) -> list[str]:
        return ["/review"]

    async def expand_custom_command(self, name: str, arguments: str) -> str:
        self.expanded_commands.append((name, arguments))
        return f"{name} {arguments}"

    def skills(self) -> list[str]:
        return ["skill"]

    def plugins(self) -> list[str]:
        return ["plugin"]


class AwaitingApprovalFrontendPorts(FakeFrontendPorts):
    """A turn that stops on an approval and resumes when it is answered.

    A transport that claims to carry an approval has to be tested against a turn
    that is actually blocked on one — otherwise the test proves only that a
    method accepts a value.

    The fake honours the same rule the application does: the decision must name the
    request the turn announced, and only once. That is what lets a test show a stale
    answer being refused rather than quietly applied.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.started = asyncio.Event()
        self.decision: frontend.Decision | None = None
        self.pending_request_id = "approval-1"
        self._answers: asyncio.Queue[frontend.Decision] = asyncio.Queue(maxsize=1)

    async def run_turn(
        self,
        text: str,
        notifications: frontend.Channel[frontend.ConversationNotification],
        cancellation: frontend.Cancellation,
    ) -> frontend.Failure | None:
        self.queries.append(text)
        self.last_turn = (notifications, cancellation)
        notifications.put(
            frontend.ToolApprovalRequested(
                tool_call=frontend.ToolCall(id="call-1", name="run_command", input='{"command": "ls"}'),
                request=frontend.PermissionRequest(tool_name="run_command", command="ls", reason="writes files"),
                request_id=self.pending_request_id,
                batch_index=0,
                batch_total=1,
            )
        )
        self.started.set()
        # Wait for either answer, the way the runtime does: a cancelled turn must
        # not stay blocked on a decision that will never come.
        answered = asyncio.ensure_future(self._answers.get())
        cancelled = asyncio.ensure_future(cancellation.wait())
        done, pending = await asyncio.wait({answered, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        for waiter in pending:
            waiter.cancel()
        if answered in done:
            self.decision = answered.result()
            notifications.put(frontend.ToolApprovalCleared(request_id=self.pending_request_id))
        notifications.close()
        return None

    async def approve(self, decision: frontend.Decision, request_id: str = "") -> frontend.ApprovalReceipt:
        self.approvals.append((request_id, decision))
        if request_id != self.pending_request_id:
            return frontend.ApprovalReceipt.rejected(request_id, "that request is no longer pending")
        self.pending_request_id = ""
        await self._answers.put(decision)
        return frontend.ApprovalReceipt.accepted(request_id)

    async def steer(self, text: str) -> frontend.SteeringReceipt:
        self.steers.append(text)
        return frontend.SteeringReceipt.held(f"steer-{len(self.steers)}")

    async def queue(self, text: str) -> frontend.QueuedReceipt:
        self.queued.append(text)
        return frontend.QueuedReceipt.queued(f"queue-{len(self.queued)}")


class InteractionOnly:
    """Expose only interaction capabilities from a scripted frontend contract."""

    def __init__(self, frontend_ports: FakeFrontendPorts) -> None:
        self._frontend_ports = frontend_ports

    def snapshot(self) -> frontend.ConversationView:
        return self._frontend_ports.snapshot()

    async def attach(self, path: str) -> frontend.AttachmentSummary:
        return await self._frontend_ports.attach(path)

    async def pending_attachments(self) -> tuple[frontend.AttachmentSummary, ...]:
        return await self._frontend_ports.pending_attachments()

    async def run_turn(
        self,
        text: str,
        notifications: frontend.Channel[frontend.ConversationNotification],
        cancellation: frontend.Cancellation,
    ) -> frontend.Failure | None:
        return await self._frontend_ports.run_turn(text, notifications, cancellation)

    async def steer(self, text: str) -> frontend.SteeringReceipt:
        return await self._frontend_ports.steer(text)

    async def queue(self, text: str) -> frontend.QueuedReceipt:
        return await self._frontend_ports.queue(text)

    async def approve(self, decision: frontend.Decision, request_id: str = "") -> frontend.ApprovalReceipt:
        return await self._frontend_ports.approve(decision, request_id)

    async def cancel(self) -> frontend.Failure | None:
        return await self._frontend_ports.cancel()
