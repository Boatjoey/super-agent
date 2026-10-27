"""The app's update: one message in, the model and its commands out.

Message routing order and key dispatch order are both load-bearing — they decide
which feature sees a key first — so both are fixed:

* messages: window size, then feature results, then a key press, then a
  conversation notification, then a finished turn;
* keys: help overlay, then approval, then the root's own keys, then the
  transcript, then the composer.

One shape difference: ``update`` is a coroutine. The key branch reaches the
command feature, which awaits its ports, so the caller awaits the update.
"""

from __future__ import annotations

from super_agent.tui import actions, attachments, commands, runtime
from super_agent.tui.app import App, ConversationNotificationMsg, Msg, SubmitDone
from super_agent.tui.approval import Request
from super_agent.tui.composer import IntentKind, QueuedEntry
from super_agent.tui.conversation import (
    ACCEPTED,
    CANCELLED,
    QUEUED,
    STEERING_HELD,
    AgentStatus,
    AgentStatusChanged,
    Cancellation,
    Channel,
    ConversationError,
    ConversationNotification,
    Failure,
    MessageAppended,
    QueuedInputAccepted,
    QueuedInputWithdrawn,
    SteeringAccepted,
    SteeringWithdrawn,
    StreamChunkReceived,
    ToolApprovalCleared,
    ToolApprovalRequested,
    UsageReported,
)
from super_agent.tui.transcript import ROLE_ASSISTANT

__all__ = [
    "finishSubmit",
    "pendingAttachments",
    "queueInput",
    "resize",
    "runTurn",
    "steerInput",
    "submitPrompt",
    "submitText",
    "update",
    "updateAttachments",
    "updateCommands",
    "updateConversationNotification",
    "updateKey",
    "waitForNotification",
]

#: The keys that reach the root even while the approval menu is open.
_CANCEL_KEYS = ("ctrl+c", "esc")


async def update(app: App, message: Msg) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Route one message in the fixed dispatch order the app relies on."""
    if isinstance(message, runtime.WindowSizeMsg):
        return resize(app, message)
    if isinstance(message, actions.ClipboardDone):
        return actions.finishCopy(app, message), ()
    if isinstance(message, (attachments.Loaded, attachments.Attached)):
        return updateAttachments(app, message)
    if isinstance(message, (commands.CompactDone, commands.MCPDone)):
        return await updateCommands(app, message)
    if isinstance(message, runtime.KeyMsg):
        return await updateKey(app, message.key)
    if isinstance(message, ConversationNotificationMsg):
        if message.turn != app.turn:
            # A stale listener on a replaced turn channel delivered a leftover
            # notification after a new turn started. Drop it and keep listening
            # on the current channel.
            return app, (waitForNotification(app.notifications, app.turn),)
        return updateConversationNotification(app, message.notification)
    if isinstance(message, SubmitDone):
        return finishSubmit(app, message.err)
    # Everything else would belong to the composer, where only the textarea's
    # own messages live. This composer has none, so there is nothing to do.
    return app, ()


def resize(app: App, message: runtime.WindowSizeMsg) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Take the terminal's new dimensions and re-derive every budget."""
    app.width, app.height = max(1, message.width), max(1, message.height)
    app.ready = True
    app.composer.set_width(app.width)
    app.composer.set_compact_palette(app.height < 18)
    app.transcript.set_width(app.width)
    return app, ()


def updateAttachments(
    app: App, message: attachments.Loaded | attachments.Attached
) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Apply an attachment result: a load is silent, an attach reports."""
    model, outcome = app.attachments.update(message)
    app.attachments = model
    if outcome is None:
        return app, ()
    if outcome.err is not None:
        app.err = f"Attach failed: {outcome.err}"
        return app, ()
    app.err = ""
    attached = outcome.attached
    if attached is not None:
        app.status = f"Attached {attached.name} ({attached.mime})"
    return app, ()


async def updateCommands(
    app: App, message: commands.CompactDone | commands.MCPDone
) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Apply a background command's result through the root's routing table."""
    model, outcome = app.commands.update(message)
    app.commands = model
    return await _applyOutcome(app, outcome, ())


async def updateKey(app: App, key: str) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Dispatch one key press, from the most global owner to the most focused."""
    if app.showHelp:
        if key in ("?", "esc"):
            app.showHelp = False
        return app, ()
    if app.approval.active() and key not in _CANCEL_KEYS:
        _, decision, submitted = app.approval.update(key)
        if submitted:
            app.transcript.clear_streaming()
            receipt = await app.turnPort.approve(decision, app.approvalRequestID)
            if receipt.status != ACCEPTED:
                # The decision answered nothing: the request it named is gone, or a
                # second click raced the first. Saying so is the point — silently
                # dropping it would look like the tool ran under that answer.
                app.err = f"Approval not applied: {receipt.reason}"
        return app, ()
    match key:
        case "ctrl+c":
            if app.approval.active() or app.cancellation is not None:
                return await actions.cancelRun(app), ()
            return app, (runtime.QUIT,)
        case "esc":
            if app.approval.active() or app.cancellation is not None:
                return await actions.cancelRun(app), ()
        case "ctrl+l":
            app.err = ""
            app.status = ""
            return app, (runtime.CLEAR_SCREEN,)
        case "?":
            if app.composer.draft() == "":
                app.showHelp = True
                app.status = ""
                return app, ()
        case "pgup" | "pgdown":
            # Page keys belong to the terminal's own scrollback.
            return app, ()
        case _:
            # Every other key belongs to the transcript, and then the composer.
            # ``ctrl+y`` is deliberately one of them: the copy binding is the
            # transcript's, not the root's.
            pass
    model, intent, consumed = app.transcript.update(key)
    app.transcript = model
    if consumed:
        if intent is None:
            return app, ()
        if intent.error:
            app.err, app.status = intent.error, ""
            return app, ()
        app.err = ""
        return app, runtime.batch(actions.copyCommand(app, intent.copy_text))
    app.composer.set_turn_running(app.cancellation is not None)
    composer, composerIntent = app.composer.update(key)
    app.composer = composer
    if composerIntent is None:
        return app, ()
    match composerIntent.kind:
        case IntentKind.SUBMIT:
            return await submitText(app, composerIntent.text)
        case IntentKind.QUEUE:
            return await queueInput(app, composerIntent.text)
        case IntentKind.STEER:
            return await steerInput(app, composerIntent.text)
        case IntentKind.CLEAR:
            app.status = "Input cleared"
        case _:
            # ``NO_INTENT`` never reaches here: an absent intent is tested above.
            pass
    return app, ()


def updateConversationNotification(
    app: App, notification: ConversationNotification
) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Apply one notification, then re-arm the listener for the next one."""
    if isinstance(notification, AgentStatusChanged):
        app.agentStatus = notification.status
        app.transcript.set_busy(notification.status.busy)
        if not app.needsInput():
            app.approval.clear()
    elif isinstance(notification, ToolApprovalRequested):
        request = notification.request
        app.approvalRequestID = notification.request_id
        app.approval.open(
            Request(
                tool_name=notification.tool_call.name,
                input=notification.tool_call.input,
                command_class=request.command_class,
                cwd=request.cwd,
                touched_paths=request.touched_paths,
                reason=request.reason,
                batch_index=notification.batch_index,
                batch_total=notification.batch_total,
            )
        )
    elif isinstance(notification, ToolApprovalCleared):
        app.approvalRequestID = ""
        app.approval.clear()
    elif isinstance(notification, MessageAppended):
        app.transcript.append(notification.message)
        if notification.message.role == ROLE_ASSISTANT:
            app.transcript.clear_streaming()
    elif isinstance(notification, ConversationError):
        if notification.failure.code != CANCELLED:
            app.err = notification.failure.message
    elif isinstance(notification, StreamChunkReceived):
        app.transcript.set_streaming(notification.message)
    elif isinstance(notification, SteeringAccepted):
        # The input is in the transcript now; the line says which step took it up,
        # because "sent" and "taken up" are not the same moment.
        app.status = f"Steering accepted at step {notification.step}"
    elif isinstance(notification, SteeringWithdrawn):
        app.err = "Steering input discarded: the turn ended before the next step"
    elif isinstance(notification, QueuedInputAccepted):
        # The application started the turn this input was waiting for. The entry
        # leaves the footer because the input is no longer waiting for anything.
        app.composer.take_queued(notification.input_id)
        app.status = f"Queued input started turn {notification.turn}"
    elif isinstance(notification, QueuedInputWithdrawn):
        app.composer.take_queued(notification.input_id)
        app.err = "Queued message discarded: the turn it waited for was cancelled"
    elif isinstance(notification, UsageReported):
        # The status line draws the most recent call's cost, so a later report
        # replaces an earlier one rather than accumulating.
        app.contextUsage = notification.usage
    return app, (waitForNotification(app.notifications, app.turn),)


async def submitText(app: App, text: str) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Route submitted input to the feature that owns its meaning.

    Slash commands belong to the command feature; everything else starts a turn.
    """
    if app.commands.is_compacting() or app.commands.managing_mcp():
        app.status = "Background operation in progress…"
        return app, ()
    if not commands.is_command(text):
        return submitPrompt(app, text)
    app.composer.clear_input()
    model, outcome, command = await app.commands.handle(
        commands.Input(text=text, attachments=pendingAttachments(app.attachments.queued_items()))
    )
    app.commands = model
    return await _applyOutcome(app, outcome, runtime.batch(command))


async def queueInput(app: App, text: str) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Queue a follow-up for after the running turn, through the application.

    The queue belongs to the application, not to this footer: the turn that takes
    the input up is started there, and the same stream that reports it also decides
    when the entry leaves the display. The draft is cleared only once the
    application says it holds the input, exactly as for steering, so a refusal
    leaves the user's text where it was.
    """
    if app.commands.is_compacting():
        app.status = "Compacting conversation…"
        return app, ()
    if commands.is_command(text):
        app.err = "Slash commands are unavailable while a turn is running"
        return app, ()
    receipt = await app.turnPort.queue(text)
    if receipt.status != QUEUED:
        app.err = f"Not queued: {receipt.reason}"
        app.status = ""
        return app, ()
    app.composer.enqueue(QueuedEntry(id=receipt.input_id, text=text))
    app.composer.clear_input()
    app.err = ""
    app.status = "Queued · waiting for the next turn"
    return app, ()


async def steerInput(app: App, text: str) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Submit an in-turn input for the next step of the running turn.

    Not a cancellation: the turn keeps running and takes the input up at its next
    step boundary, which the runtime reports back as an acceptance naming the
    step. The draft is cleared only once the runtime holds the input, so a refusal
    leaves the user's text where it was.
    """
    if commands.is_command(text):
        app.err = "Slash commands are unavailable while a turn is running"
        return app, ()
    receipt = await app.turnPort.steer(text)
    if receipt.status != STEERING_HELD:
        app.err = f"Steering not accepted: {receipt.reason}"
        return app, ()
    app.composer.clear_input()
    app.err = ""
    app.status = "Steering · waiting for the next step"
    return app, ()


def pendingAttachments(items: tuple[attachments.Item, ...]) -> tuple[commands.Attachment, ...]:
    """The queue, in the vocabulary the command feature owns."""
    return tuple(commands.Attachment(name=item.name, mime=item.mime) for item in items)


def finishSubmit(app: App, err: Failure | None) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Close out a submission the application has finished running.

    Nothing is started here. A queued follow-up becomes the next turn inside the
    application, on this same notification channel, so by the time this arrives
    every input the user queued has either run or been withdrawn.

    A cancelled submission is not an error to shout about: the user asked for it,
    and the status line already says so.
    """
    app.cancellation = None
    app.composer.set_turn_running(False)
    if err is not None and err.code != CANCELLED:
        app.err = err.message
    return app, ()


def submitPrompt(app: App, text: str) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Start a turn: fresh channels, a fresh cancellation, and a new turn number."""
    app.err = ""
    app.status = ""
    app.transcript.clear_streaming()
    app.agentStatus = AgentStatus(label="Submitting", busy=True)
    app.transcript.set_busy(True)
    app.approval.clear()
    app.composer.clear_input()
    app.composer.set_turn_running(True)
    app.attachments.set(())
    # Captured now, because the next turn replaces them on the app.
    notifications: Channel[ConversationNotification] = Channel()
    cancellation = Cancellation()
    app.notifications = notifications
    app.cancellation = cancellation
    app.approvalRequestID = ""
    app.turn += 1
    return app, (
        waitForNotification(notifications, app.turn),
        runTurn(app, text, notifications, cancellation),
    )


def runTurn(
    app: App,
    text: str,
    notifications: Channel[ConversationNotification],
    cancellation: Cancellation,
) -> runtime.Command[Msg]:
    """The command that runs the submission and reports how it ended."""

    async def run() -> Msg:
        err = await app.turnPort.run_turn(text, notifications, cancellation)
        return SubmitDone(err=err)

    return run


def waitForNotification(channel: Channel[ConversationNotification], turn: int) -> runtime.Listener[Msg]:
    """The listener command for one turn's notification channel.

    It ends when the channel closes, which is what stops the chain: a closed
    channel yields no message, and returning ``None`` ends the listener.
    """

    async def listen() -> Msg | None:
        notification = await channel.get()
        if notification is None:
            return None
        return ConversationNotificationMsg(notification=notification, turn=turn)

    return runtime.Listener(listen)


async def _applyOutcome(
    app: App, outcome: commands.Outcome | None, command: tuple[runtime.Command[Msg], ...]
) -> tuple[App, tuple[runtime.Command[Msg], ...]]:
    """Deferred: the package surface imports this module, so it is patched in late."""
    from super_agent.tui import applyOutcome

    return await applyOutcome(app, outcome, command)
