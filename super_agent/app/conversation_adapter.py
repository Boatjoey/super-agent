"""The runtime application API behind every front-end port.

Conversion lives at the composition edge, so neither side knows the other: a
front end sees only the contract's display DTOs, and the runtime only knows its
own notifications and views. There is exactly one such edge, which is why the
terminal and the web interface cannot drift apart in what a
conversation looks like.

Two things this file is the single home of:

* the mapping from runtime states and notifications to presentation values. A
  notification kind the mapping does not know becomes a visible
  :class:`frontend.ConversationError` naming the type, rather than being dropped, so a
  new runtime notification cannot degrade an interface without a trace.
* the two bridges of a turn. The runtime channels are attached to the front end's
  channels by coroutines over queues, and the run context is built from the turn's
  :class:`frontend.Cancellation` so the runtime still sees one cancellation signal.

A front end that is not in this process — a browser — still calls the same
object: :class:`super_agent.web` is a transport over this port, not a second
adapter.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import uuid

from super_agent import frontend, runtime
from super_agent.app.agents import AgentController
from super_agent.app.mcp import MCPController
from super_agent.app.memory import MemoryController
from super_agent.errors import Cancelled, JoinedError, errors_is
from super_agent.runtime.machine.queued import QueuedInput
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.session import ApprovalsClosed, NotificationsClosed

__all__ = [
    "ConversationAdapter",
    "new_conversation_adapter",
    "to_conversation_notification",
    "to_conversation_view",
    "to_frontend_context_usage",
    "to_frontend_message",
    "to_frontend_message_ptr",
    "to_frontend_permission",
    "to_frontend_status",
    "to_frontend_tool_call",
]


class ConversationAdapter:
    """The conversation port the three front ends talk to."""

    __slots__ = (
        "_approvalSink",
        "_pendingApproval",
        "_sandboxDowngraded",
        "agents",
        "mcp",
        "memory",
        "session",
    )

    def __init__(self, session: runtime.Session, *controllers: object, sandbox_downgraded: bool = False) -> None:
        self.session = session
        self.mcp: MCPController | None = None
        self.agents: AgentController | None = None
        #: The memory switch, when the application wired one. Without it the
        #: session's own port is still the truth about what is remembered.
        self.memory: MemoryController | None = None
        #: Whether the strict sandbox was downgraded to ``off`` on this platform,
        #: reported to the interface so the operator sees commands run unsandboxed.
        self._sandboxDowngraded = sandbox_downgraded
        #: Where a decision goes while a turn runs, and which request it answers.
        #: Both are per turn: the sink exists only between the turn's start and its
        #: end, so an answer offered outside a turn is refused rather than buffered
        #: for a turn that has not begun.
        self._approvalSink: asyncio.Queue[runtime.ApprovalDecision | ApprovalsClosed] | None = None
        self._pendingApproval: str = ""
        for controller in controllers:
            match controller:
                case MCPController():
                    self.mcp = controller
                case AgentController():
                    self.agents = controller
                case MemoryController():
                    self.memory = controller
                case _:
                    # An unrecognised controller is not an error: a caller may pass
                    # anything, so the default is silent.
                    pass

    # --- agent profiles ------------------------------------------------------

    def list_agents(self) -> list[frontend.AgentSummary]:
        """Every configured profile, or nothing when the controller is absent."""
        if self.agents is None:
            return []
        return [
            frontend.AgentSummary(
                name=profile.name,
                provider=profile.provider,
                model=profile.model,
                permission_mode=str(profile.permission_mode),
            )
            for profile in self.agents.list()
        ]

    def current_agent(self) -> frontend.AgentSummary:
        """The active profile, or an empty summary when there is no controller."""
        if self.agents is None:
            return frontend.AgentSummary()
        profile = self.agents.active_profile()
        return frontend.AgentSummary(
            name=profile.name,
            provider=profile.provider,
            model=profile.model,
            permission_mode=str(profile.permission_mode),
        )

    async def use_agent(self, name: str) -> None:
        """Switch profiles, replacing the context, model, and visible tools."""
        if self.agents is None:
            raise ValueError("agent profiles are unavailable")
        await self.agents.use(name)

    # --- provider configuration ---------------------------------------------

    def list_providers(self) -> list[frontend.ProviderView]:
        """Every configured provider, credential redacted to a presence flag."""
        if self.agents is None:
            return []
        return [
            frontend.ProviderView(
                name=name,
                model=config.model,
                base_url=config.base_url,
                has_key=_has_credential(name, config.api_key),
            )
            for name, config in sorted(self.agents.providers.items())
        ]

    def provider(self, name: str) -> frontend.ProviderView:
        """One provider's configuration, credential redacted."""
        if self.agents is None:
            return frontend.ProviderView()
        config = self.agents.provider_config(name)
        return frontend.ProviderView(
            name=name,
            model=config.model,
            base_url=config.base_url,
            has_key=_has_credential(name, config.api_key),
        )

    async def configure_provider(self, name: str, api_key: str, model: str = "") -> None:
        """Set a provider's key (and model), persisting and rebuilding the model."""
        if self.agents is None:
            raise ValueError("provider configuration is unavailable")
        await self.agents.configure_provider(name, api_key, model)

    # --- conversation --------------------------------------------------------

    async def fork(self, title: str) -> str:
        meta = await self.session.fork(title)
        return str(meta.id)

    async def memories(self) -> list[str]:
        return self.session.memories()

    async def remember(self, text: str) -> None:
        await self.session.remember(text)

    async def forget_memories(self) -> None:
        await self.session.forget_memories()

    def memory_enabled(self) -> bool:
        """Whether the cross-session memory is in use right now."""
        if self.memory is not None:
            return self.memory.enabled
        return self.session.memory.enabled

    def memory_backend(self) -> str:
        """Where the memory lines live, by name."""
        if self.memory is not None:
            return self.memory.backend
        return self.session.memory.name

    async def set_memory_enabled(self, enabled: bool) -> None:
        """Turn the cross-session memory on or off, and make it take effect at once.

        The stored lines are left alone either way, so turning the memory back on
        brings back exactly what was there before.
        """
        if self.memory is None:
            raise ValueError("the memory switch is not available")
        await self.memory.setEnabled(enabled)

    async def export(self, format: str) -> str:
        return self.session.export(format)

    async def attach(self, path: str) -> frontend.AttachmentSummary:
        attachment = self.session.attach(path)
        return frontend.AttachmentSummary(name=attachment.name, mime=attachment.mime)

    async def pending_attachments(self) -> tuple[frontend.AttachmentSummary, ...]:
        return tuple(
            frontend.AttachmentSummary(name=attachment.name, mime=attachment.mime)
            for attachment in self.session.pending_attachments()
        )

    def snapshot(self) -> frontend.ConversationView:
        """The view a front end rebuilds from, including the pending request's id.

        The id is stamped here because it is the application that named the
        request: a tab that reconnects mid-approval still has to answer it, and an
        id it cannot read is an approval it cannot give.
        """
        view = to_conversation_view(self.session.snapshot())
        return dataclasses.replace(view, pending_approval_id=self._pendingApproval)

    def config_view(self) -> frontend.ConfigView:
        """The application's identity, policy, and the operations it performs.

        Everything is read back from the session and its controllers, so the
        display cannot describe a policy the runtime is not using. Capabilities are
        the operations this instance can actually perform: a controller that is
        absent takes its capabilities with it.
        """
        agent = self.current_agent()
        meta = self.session.meta
        workspace = self.session.workspace
        # Read the workspace through its spec, which is the shape the session
        # itself persists and the only one its port promises. Reaching for the
        # concrete workspace object's helpers would type-check here and break
        # against any other implementation of the port.
        spec = None if workspace is None else workspace.spec()
        capabilities = [
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
        ]
        if self.agents is not None:
            capabilities.append("agents")
        if self.mcp is not None:
            capabilities.append("mcp")
        if self.memory is not None or self.session.memory.enabled:
            capabilities.append("memory")
        # The credential is missing when the active provider resolved to an empty
        # key. It is read from the controller's resolved table, not the raw
        # settings, so a key supplied through the environment does not read as
        # missing.
        credential_missing = False
        if self.agents is not None:
            active_provider = self.agents.active_profile().provider
            credential_missing = self.agents.provider_config(active_provider).api_key == ""
        return frontend.ConfigView(
            session_id=str(meta.id),
            session_title=meta.title,
            workspace="" if spec is None else spec.cwd,
            roots=() if spec is None else tuple(root.path for root in spec.roots),
            instruction_sources=meta.instruction_sources,
            agent=agent.name,
            provider=agent.provider,
            model=agent.model,
            permission_mode=self.permission_mode(),
            auto_approve=self.auto_approve_tools(),
            agents=tuple(self.list_agents()),
            memory_enabled=self.memory_enabled(),
            memory_backend=self.memory_backend(),
            credential_missing=credential_missing,
            sandbox_downgraded=self._sandboxDowngraded,
            capabilities=tuple(capabilities),
        )

    async def approve(self, decision: frontend.Decision, request_id: str = "") -> frontend.ApprovalReceipt:
        """Answer the approval ``request_id`` names, or refuse by value.

        Refusal is a value for the same reason steering's is: an answer that lost
        the race is normal, not exceptional. Every refusal names the request it was
        about, so a front end can tell "my click was too late" from "my click went
        to the wrong prompt" — and either way, no decision reaches a tool call the
        user did not see.
        """
        sink = self._approvalSink
        if sink is None:
            return frontend.ApprovalReceipt.rejected(request_id, "no turn is running")
        if not request_id:
            return frontend.ApprovalReceipt.rejected(request_id, "the decision names no approval request")
        if request_id != self._pendingApproval:
            return frontend.ApprovalReceipt.rejected(request_id, "that request is no longer pending")
        # Consumed before the hand-off: a second click on the same prompt is the
        # common way a decision arrives twice, and it must not run the tool twice.
        self._pendingApproval = ""
        await sink.put(runtime.ApprovalDecision(str(decision)))
        return frontend.ApprovalReceipt.accepted(request_id)

    async def steer(self, text: str) -> frontend.SteeringReceipt:
        """Submit an in-turn input, answering with what became of it.

        The id is minted here because the receipt is the caller's handle on the
        input: acceptance arrives later, on the turn's notification stream, and
        quotes this id. Refusal is reported as a value rather than raised, since a
        turn that ended a moment ago is a normal race, not a failure.
        """
        input_id = f"steer-{uuid.uuid4().hex[:12]}"
        if self.session.snapshot().state in (runtime.STATE_IDLE, runtime.STATE_INITIALIZING):
            return frontend.SteeringReceipt.rejected(input_id, "no turn is running")
        try:
            await self.session.submit_steering(text, input_id=input_id)
        except Exception as error:
            return frontend.SteeringReceipt.rejected(input_id, str(error) or "the runtime refused the input")
        return frontend.SteeringReceipt.held(input_id)

    async def queue(self, text: str) -> frontend.QueuedReceipt:
        """Submit an input for the next turn, answering with what became of it.

        Same shape as :meth:`steer`, and for the same reason: the input is not a
        turn yet, so the receipt can only say it is waiting. The turn it becomes is
        reported later, as
        :class:`super_agent.frontend.QueuedInputAccepted`.

        A refusal here means there is nothing to wait behind. The idle case is
        checked first because it is the common race — the turn ended between the
        keystroke and this call — and its reason tells the caller what to do
        instead.
        """
        input_id = f"queue-{uuid.uuid4().hex[:12]}"
        if self.session.snapshot().state in (runtime.STATE_IDLE, runtime.STATE_INITIALIZING):
            return frontend.QueuedReceipt.rejected(input_id, "no turn is running")
        try:
            await self.session.submit_queued(text, input_id=input_id)
        except Exception as error:
            return frontend.QueuedReceipt.rejected(input_id, str(error) or "the runtime refused the input")
        return frontend.QueuedReceipt.queued(input_id)

    async def cancel(self) -> frontend.Failure | None:
        """Cancel the turn in flight, reporting rather than raising a failure."""
        try:
            await self.session.cancel()
        except Exception as error:
            return frontend.failure_from(error, operation="cancel")
        return None

    async def reset(self) -> None:
        await self.session.reset()

    async def compact(self, summary: str) -> None:
        # The keep-newest default lives in the runtime session.
        await self.session.compact(live_context(), summary, 0)

    async def undo(self) -> None:
        await self.session.undo()

    async def set_permission_mode(self, mode: str) -> None:
        await self.session.set_permission_mode(runtime.PermissionMode(mode))

    def permission_mode(self) -> str:
        return str(self.session.permission_mode())

    def auto_approve_tools(self) -> bool:
        return self.session.auto_approve_tools()

    # --- saved sessions ------------------------------------------------------

    async def list_sessions(self) -> list[frontend.SessionSummary]:
        summaries = self.session.list_sessions()
        return [
            frontend.SessionSummary(
                id=str(item.id),
                title=item.title,
                provider=item.provider,
                model=item.model,
                cwd=item.cwd,
                parent_id=str(item.parent_id),
            )
            for item in summaries
        ]

    async def resume(self, session_id: str) -> None:
        await self.session.resume(runtime.SessionID(session_id))

    async def rename_session(self, session_id: str, title: str) -> None:
        self.session.rename_session(runtime.SessionID(session_id), title)

    async def delete_session(self, session_id: str) -> None:
        self.session.delete_session(runtime.SessionID(session_id))

    # --- MCP servers ---------------------------------------------------------

    def list_mcp_servers(self) -> list[frontend.MCPServerSummary]:
        if self.mcp is None:
            return []
        return [frontend.MCPServerSummary(name=server.name, tools=server.tools) for server in self.mcp.list()]

    async def add_mcp_server(self, name: str, command: str, args: list[str]) -> None:
        if self.mcp is None:
            raise ValueError("MCP management is unavailable")
        await self.mcp.add(live_context(), name, command, args)

    async def remove_mcp_server(self, name: str) -> None:
        if self.mcp is None:
            raise ValueError("MCP management is unavailable")
        await self.mcp.remove(name)

    async def restart_mcp_server(self, name: str) -> None:
        if self.mcp is None:
            raise ValueError("MCP management is unavailable")
        await self.mcp.restart(live_context(), name)

    # --- repository and extension queries ------------------------------------

    async def git_diff(self) -> str:
        if self.agents is None:
            raise ValueError("workflow tools are unavailable")
        return await self.agents.git_diff(live_context())

    async def git_status(self) -> str:
        if self.agents is None:
            raise ValueError("workflow tools are unavailable")
        return await self.agents.git_status(live_context())

    async def diagnostics(self, path: str) -> str:
        if self.agents is None:
            raise ValueError("diagnostics are unavailable")
        return await self.agents.diagnostics(live_context(), path)

    def custom_commands(self) -> list[str]:
        if self.agents is None:
            return []
        return self.agents.custom_commands()

    async def expand_custom_command(self, name: str, arguments: str) -> str:
        if self.agents is None:
            raise ValueError("custom commands are unavailable")
        return self.agents.expand_command(name, arguments)

    def skills(self) -> list[str]:
        if self.agents is None:
            return []
        return self.agents.skills()

    def plugins(self) -> list[str]:
        if self.agents is None:
            return []
        return self.agents.plugins()

    # --- the turn ------------------------------------------------------------

    async def run_turn(
        self,
        text: str,
        notifications: frontend.Channel[frontend.ConversationNotification],
        cancellation: frontend.Cancellation,
    ) -> frontend.Failure | None:
        """Run the submitted turn, and then every turn queued behind it.

        One call is one *submission*, not necessarily one turn: an input queued
        while this one runs belongs to the next turn, so when this turn ends the
        application starts that turn itself. Sequencing is a rule of the
        application, not of a renderer, which is why it happens here rather than in
        every front end that can queue.

        The notification channel spans the whole submission, so a front end keeps
        rendering one continuous conversation and learns about each new turn from
        :class:`super_agent.frontend.QueuedInputAccepted`. The channel closes when
        the last turn ends, which is what ends the caller's listener.

        Returns the failure of the last turn that ran, as a value: an interface
        that has already gone away must not be hit with an exception on its way out,
        and a front end that has to inspect an exception's type cannot tell whether
        its input was ever accepted. Each turn's own failure is already on the
        stream as a :class:`super_agent.frontend.ConversationError`.

        A cancelled submission stops the pump: the runtime has already discarded
        the queue, so there is nothing left to start.
        """
        error: frontend.Failure | None = None
        try:
            prompt, input_id = text, ""
            while True:
                error = await self._run_one_turn(prompt, input_id, notifications, cancellation)
                if cancellation.cancelled or (error is not None and error.code == frontend.CANCELLED):
                    break
                queued = self._next_queued()
                if queued is None:
                    break
                # An input the machine cannot name cannot be taken up, and starting
                # it again would loop forever. Only this application mints queued
                # ids, so this is a guard against a programming error, not a path a
                # front end can reach.
                if queued.id == "":
                    break
                prompt, input_id = queued.content, queued.id
        finally:
            notifications.close()
        return error

    def _next_queued(self) -> QueuedInput | None:
        """The input waiting for the next turn, or ``None`` when nothing waits."""
        queued = self.session.snapshot().queued
        return queued[0] if queued else None

    async def _run_one_turn(
        self,
        text: str,
        input_id: str,
        notifications: frontend.Channel[frontend.ConversationNotification],
        cancellation: frontend.Cancellation,
    ) -> frontend.Failure | None:
        """Run one turn, bridging the runtime's queues to the interface's channels.

        ``input_id`` names the queued input this turn was started from, so the
        machine can report that input's acceptance in the same commit that appends
        the message.
        """
        ctx = RunContext()
        watcher = asyncio.create_task(_watchCancellation(cancellation, ctx))
        try:
            if self.agents is not None:
                try:
                    await self.agents.run_hook(ctx, "before_turn")
                except Exception as error:
                    return frontend.failure_from(error, operation="run_turn")
            runtimeNotifications: asyncio.Queue[runtime.SessionNotification] = asyncio.Queue(maxsize=100)
            runtimeApprovals: asyncio.Queue[runtime.ApprovalDecision | ApprovalsClosed] = asyncio.Queue(maxsize=1)
            done = asyncio.Event()
            # The sink is published for the duration of the turn only: :meth:`approve`
            # reads it, so an answer offered outside a turn is refused rather than
            # buffered for a turn that has not started.
            self._approvalSink = runtimeApprovals
            notificationBridge = asyncio.create_task(
                self._bridgeNotifications(ctx, notifications, runtimeNotifications, done)
            )
            error: BaseException | None = None
            try:
                await self.session.run_turn(ctx, text, runtimeNotifications, runtimeApprovals, input_id)
            except Exception as failure:
                error = failure
            finally:
                done.set()
                self._approvalSink = None
                self._pendingApproval = ""
                # The notification bridge drains what the turn produced and then
                # returns, which is what guarantees this turn's events are on the
                # channel before the next turn's begin.
                await notificationBridge
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        if self.agents is not None:
            hookCtx = RunContext()
            if error is not None:
                error = _join(error, await _hookFailure(self.agents, hookCtx, ("error",)))
            error = _join(error, await _hookFailure(self.agents, hookCtx, ("turn_complete", "after_turn")))
        return frontend.failure_from(
            error,
            operation="run_turn",
            cancelled=errors_is(error, Cancelled),
        )

    async def _bridgeNotifications(
        self,
        ctx: RunContext,
        notifications: frontend.Channel[frontend.ConversationNotification],
        runtimeNotifications: asyncio.Queue[runtime.SessionNotification],
        done: asyncio.Event,
    ) -> None:
        """Forward one turn's runtime notifications onto the interface's channel.

        It stops when the runtime closes the queue *or* when the turn is over and
        the queue has drained, so an event the runtime could not enqueue cannot
        leave the interface's listener waiting forever. It does not close the
        channel: one channel spans the submission, which may be several turns, so
        only the pump above decides when the stream is over.
        """
        while True:
            getter = asyncio.ensure_future(runtimeNotifications.get())
            stopper = asyncio.ensure_future(done.wait())
            finished, _pending = await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if getter in finished:
                notification = getter.result()
                if not stopper.done():
                    stopper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stopper
                if isinstance(notification, NotificationsClosed):
                    return
                if isinstance(notification, runtime.ToolApprovalRequested) and self.agents is not None:
                    try:
                        await self.agents.run_hook(ctx, "approval_requested")
                    except Exception as hookError:
                        notifications.put(
                            frontend.ConversationError(
                                failure=frontend.Failure(
                                    message=str(hookError) or type(hookError).__name__,
                                    code=frontend.FAILED,
                                    operation="approval_requested",
                                )
                            )
                        )
                notifications.put(self._correlate(to_conversation_notification(notification)))
                continue
            getter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await getter
            return

    def _correlate(self, notification: frontend.ConversationNotification) -> frontend.ConversationNotification:
        """Name one approval request, and forget it when it ends.

        The runtime does not number approvals: to the state machine one waiting
        tool call is the next one, not the third. Naming them is therefore the
        application's job, and this is where it happens — every announced request
        gets an id, and :meth:`approve` accepts exactly that id, once.
        """
        if isinstance(notification, frontend.ToolApprovalRequested):
            request_id = f"approval-{uuid.uuid4().hex[:12]}"
            self._pendingApproval = request_id
            return dataclasses.replace(notification, request_id=request_id)
        if isinstance(notification, frontend.ToolApprovalCleared):
            request_id, self._pendingApproval = self._pendingApproval, ""
            return dataclasses.replace(notification, request_id=request_id)
        return notification


def new_conversation_adapter(
    session: runtime.Session, *controllers: object, sandbox_downgraded: bool = False
) -> ConversationAdapter:
    """The session, plus whichever controllers apply."""
    return ConversationAdapter(session, *controllers, sandbox_downgraded=sandbox_downgraded)


async def _watchCancellation(cancellation: frontend.Cancellation, ctx: RunContext) -> None:
    """Cancel the run context when the interface cancels the turn."""
    await cancellation.wait()
    ctx.cancel()


async def _hookFailure(agents: AgentController, ctx: RunContext, events: tuple[str, ...]) -> BaseException | None:
    """Run lifecycle hooks, returning their failure instead of raising it."""
    try:
        await agents.run_hooks(ctx, *events)
    except Exception as error:
        return error
    return None


def _join(error: BaseException | None, other: BaseException | None) -> BaseException | None:
    """Join two optional errors: one error, or both joined."""
    if error is None:
        return other
    if other is None:
        return error
    return JoinedError(error, other)


def _has_credential(provider: str, api_key: str) -> bool:
    """Whether ``api_key`` is a real credential rather than empty or a placeholder.

    The settings template writes ``sk-...`` / ``sk-ant-...`` as a stand-in; those
    are "unset", not secrets, so a presence flag built from them must not read as
    "a key is present".
    """
    if api_key == "":
        return False
    if provider == "claude":
        return api_key != "sk-ant-..."
    return api_key != "sk-..."


# --- the mapping table -------------------------------------------------------


def to_conversation_notification(
    notification: runtime.SessionNotification,
) -> frontend.ConversationNotification:
    """Map one runtime notification to the interface's own kind.

    An unknown kind becomes a :class:`frontend.ConversationError` naming its type.
    Dropping it would let a new runtime notification degrade the interface with
    nothing to show for it, which is the failure this default exists to prevent.
    """
    match notification:
        case runtime.StateChanged():
            return frontend.AgentStatusChanged(status=to_frontend_status(notification.state))
        case runtime.ToolApprovalRequested():
            return frontend.ToolApprovalRequested(
                tool_call=to_frontend_tool_call(notification.tool_call),
                request=to_frontend_permission(notification.request),
                batch_index=notification.batch_index,
                batch_total=notification.batch_total,
            )
        case runtime.ToolApprovalCleared():
            return frontend.ToolApprovalCleared()
        case runtime.StreamChunkReceived():
            return frontend.StreamChunkReceived(message=to_frontend_message_ptr(notification.message))
        case runtime.MessageAppended():
            return frontend.MessageAppended(message=to_frontend_message(notification.message))
        case runtime.UsageReported():
            return frontend.UsageReported(usage=to_frontend_context_usage(notification.usage))
        case runtime.SteeringAccepted():
            return frontend.SteeringAccepted(input_id=notification.input_id, step=notification.step)
        case runtime.SteeringWithdrawn():
            return frontend.SteeringWithdrawn(input_id=notification.input_id)
        case runtime.QueuedInputAccepted():
            return frontend.QueuedInputAccepted(input_id=notification.input_id, turn=notification.turn)
        case runtime.QueuedInputWithdrawn():
            return frontend.QueuedInputWithdrawn(input_id=notification.input_id)
        case runtime.SessionError():
            return frontend.ConversationError(
                failure=frontend.failure_from(notification.err, operation="run_turn") or frontend.Failure()
            )
        case _:
            return frontend.ConversationError(
                failure=frontend.Failure(
                    message=f"unknown runtime session notification: {type(notification).__name__}",
                    code=frontend.FAILED,
                    operation="run_turn",
                )
            )


def to_conversation_view(view: runtime.EngineView) -> frontend.ConversationView:
    """Map one engine snapshot to the view the transcript rebuilds from."""
    result = frontend.ConversationView(
        agent_status=to_frontend_status(view.state),
        messages=tuple(to_frontend_message(message) for message in view.messages),
        pending_tool_batch_index=view.pending_tool_batch_index,
        pending_tool_batch_total=view.pending_tool_batch_total,
        streaming_message=to_frontend_message_ptr(view.streaming_message),
    )
    if view.pending_tool is not None:
        result = dataclasses.replace(result, pending_tool=to_frontend_tool_call(view.pending_tool))
    if view.pending_permission is not None:
        result = dataclasses.replace(result, pending_permission=to_frontend_permission(view.pending_permission))
    return result


def to_frontend_context_usage(usage: runtime.Usage) -> frontend.ContextUsage:
    """One provider report, unchanged: the counts already mean the same thing."""
    return frontend.ContextUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


def to_frontend_status(state: runtime.State) -> frontend.AgentStatus:
    """The presentation status for one runtime state.

    The table is exhaustive over the runtime states; a state it does not name is
    reported as ``Unknown`` rather than borrowing a neighbouring label.
    Presentation words, not runtime words, are the whole point: the CLI owns no
    runtime state enum.
    """
    match state:
        case runtime.STATE_INITIALIZING:
            return frontend.AgentStatus(label="Initializing", busy=True)
        case runtime.STATE_IDLE:
            return frontend.AgentStatus(label="Idle")
        case runtime.STATE_WAITING_LLM:
            return frontend.AgentStatus(label="WaitingLLM", busy=True)
        case runtime.STATE_WAITING_APPROVAL:
            return frontend.AgentStatus(label="WaitingApproval", awaiting_approval=True)
        case runtime.STATE_RUNNING_TOOL:
            return frontend.AgentStatus(label="RunningTool", busy=True)
        case runtime.STATE_ADVANCING_QUEUE:
            return frontend.AgentStatus(label="AdvancingQueue", busy=True)
        case _:
            return frontend.AgentStatus(label="Unknown")


def to_frontend_message_ptr(message: runtime.Message | None) -> frontend.Message | None:
    """A message as a presentation value, or ``None`` for no message."""
    if message is None:
        return None
    return to_frontend_message(message)


def to_frontend_message(message: runtime.Message) -> frontend.Message:
    """One message in the transcript's vocabulary.

    The runtime type is a flat tuple with no nil entries, so there is nothing to
    skip.
    """
    calls = tuple(to_frontend_tool_call(call) for call in message.tool_calls or ())
    attachments = tuple(
        frontend.Attachment(name=attachment.name, mime=attachment.mime) for attachment in message.attachments
    )
    return frontend.Message(
        role=frontend.Role(str(message.role)),
        content=message.content,
        reasoning_content=message.reasoning_content,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        tool_calls=calls,
        interrupted=message.interrupted,
        attachments=attachments,
    )


def to_frontend_tool_call(call: runtime.ToolCall) -> frontend.ToolCall:
    """One tool call, unchanged: the fields already mean the same thing."""
    return frontend.ToolCall(id=call.id, name=call.name, input=call.input)


def to_frontend_permission(request: runtime.PermissionRequest) -> frontend.PermissionRequest:
    """One permission request, with its sequences copied."""
    return frontend.PermissionRequest(
        tool_name=request.tool_name,
        command=request.command,
        command_class=str(request.command_class),
        cwd=request.cwd,
        touched_paths=tuple(request.touched_paths),
        env_vars=tuple(request.env_vars),
        reason=request.reason,
    )
