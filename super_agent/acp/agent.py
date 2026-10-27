"""The agent half of the Agent Client Protocol.

One ACP session is one conversation. A prompt is a turn; its streamed text becomes
``agent_message_chunk`` updates, its tool calls become ``tool_call`` cards, and a
permission request becomes a ``session/request_permission`` the client answers.

Three protocol-level differences from the terminal are worth stating, because they
are choices rather than omissions:

* **Cancel replaces steering.** ACP has no "insert this after the current step", so
  ``session/cancel`` is the only way to change a turn in flight. A caller that wants
  to redirect sends ``session/cancel`` and then a new prompt.
* **Usage has no home.** The provider's token counts are not part of the protocol,
  so they are not sent; inventing a field would break a strict client.
* **A failed turn is a JSON-RPC error**, not an empty answer. ``stopReason``
  describes why a turn stopped, not that it failed, and reporting a failure as
  ``end_turn`` would tell the editor the work succeeded.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from typing import Any

from super_agent import frontend
from super_agent.acp import jsonrpc, updates
from super_agent.acp.connection import Connection
from super_agent.frontend import wire

__all__ = ["PROTOCOL_VERSION", "AcpAgent"]

#: The protocol revision this agent speaks.
PROTOCOL_VERSION = 1

#: The permission modes this agent can be told to use, with their display names.
MODES: tuple[tuple[str, str], ...] = (
    ("ask", "Ask before tools"),
    ("accept-edits", "Accept edits"),
    ("plan", "Plan only"),
    ("bypass", "Bypass permissions"),
)

#: Which option a client's ``outcome`` selects. Anything unrecognised denies:
#: approving on an ambiguous answer would run a tool nobody chose.
DECISION_BY_OPTION = updates.DECISION_BY_OPTION


@dataclasses.dataclass(slots=True)
class _Stream:
    """How much of the assistant's text has already been sent.

    The contract reports the whole accumulated message, not a delta, so the delta
    is computed here — otherwise every chunk would repeat the message so far.
    """

    text: str = ""
    reasoning: str = ""


@dataclasses.dataclass(slots=True)
class _Turn:
    """The turn in flight, and whether the client cancelled it."""

    cancellation: frontend.Cancellation
    cancelled: bool = False


class AcpAgent:
    """The protocol surface: one message in, zero or more messages out."""

    __slots__ = ("_connection", "_conversation", "_cwd", "_session_id", "_tasks", "_turn")

    def __init__(
        self,
        conversation: frontend.Conversation,
        connection: Connection,
        *,
        session_id: str,
        cwd: str = "",
    ) -> None:
        self._conversation = conversation
        self._connection = connection
        self._session_id = session_id
        self._cwd = cwd
        self._turn: _Turn | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def session_id(self) -> str:
        """The id this agent reports for the session it drives."""
        return self._session_id

    async def handle(self, message: dict[str, Any]) -> None:
        """Dispatch one incoming message.

        Requests run as tasks so that ``session/cancel`` can arrive while a prompt
        is still being answered; a response is delivered inline, because it is the
        thing a blocked request is waiting for.
        """
        if jsonrpc.is_response(message):
            self._connection.resolve(message)
            return

        method = message.get("method")
        if not isinstance(method, str):
            return
        params = message.get("params")
        arguments = params if isinstance(params, dict) else {}

        if "id" not in message:
            await self._notification(method, arguments)
            return

        task = asyncio.create_task(self._respond(message["id"], method, arguments))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shut_down(self) -> None:
        """Finish in-flight requests, then fail whatever is still pending."""
        for task in tuple(self._tasks):
            with contextlib.suppress(Exception):
                await task
        self._connection.close()

    async def _respond(self, request_id: object, method: str, params: dict[str, Any]) -> None:
        try:
            value = await self._dispatch(method, params)
        except jsonrpc.JsonRpcError as failure:
            await self._send(jsonrpc.error(_id(request_id), failure.code, failure.message))
            return
        except Exception as failure:
            await self._send(jsonrpc.error(_id(request_id), jsonrpc.INTERNAL_ERROR, wire.error_text(failure)))
            return
        await self._send(jsonrpc.result(_id(request_id), value))

    async def _notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "session/cancel":
            await self._cancel()

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        match method:
            case "initialize":
                return self._initialize()
            case "authenticate":
                # No authentication method is advertised, so any attempt is a
                # client bug rather than a credential this agent can check.
                raise jsonrpc.JsonRpcError(jsonrpc.INVALID_PARAMS, "this agent requires no authentication")
            case "session/new":
                return self._new_session(params)
            case "session/load":
                return await self._load_session(params)
            case "session/prompt":
                return await self._prompt(params)
            case "session/set_mode":
                return await self._set_mode(params)
            case _:
                raise jsonrpc.JsonRpcError(jsonrpc.METHOD_NOT_FOUND, f"unsupported method: {method}")

    # --- the methods ---------------------------------------------------------

    def _initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
                "mcpCapabilities": {"http": False, "sse": False},
            },
            "authMethods": [],
        }

    def _new_session(self, params: dict[str, Any]) -> dict[str, Any]:
        cwd = params.get("cwd")
        if isinstance(cwd, str) and cwd:
            self._cwd = cwd
        return {"sessionId": self._session_id, "modes": self._modes()}

    async def _load_session(self, params: dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise jsonrpc.JsonRpcError(jsonrpc.INVALID_PARAMS, "sessionId is required")
        await self._conversation.resume(session_id)
        self._session_id = session_id
        # The client attached to a conversation it never saw: replay the
        # transcript as the same updates a live turn would have produced.
        for message in self._conversation.snapshot().messages:
            for update in updates.message_chunks(message):
                await self._update(update)
        return None

    async def _set_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        mode = params.get("modeId")
        if not isinstance(mode, str) or mode not in {item[0] for item in MODES}:
            raise jsonrpc.JsonRpcError(jsonrpc.INVALID_PARAMS, f"unknown mode: {mode}")
        await self._conversation.set_permission_mode(mode)
        return {"modes": self._modes()}

    async def _prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._turn is not None:
            raise jsonrpc.JsonRpcError(jsonrpc.INVALID_REQUEST, "a prompt is already running in this session")
        text = _prompt_text(params)
        if not text:
            raise jsonrpc.JsonRpcError(jsonrpc.INVALID_PARAMS, "the prompt contains no text")

        notifications: frontend.Channel[frontend.ConversationNotification] = frontend.Channel()
        turn = _Turn(cancellation=frontend.Cancellation())
        self._turn = turn
        stream = _Stream()
        consumer = asyncio.create_task(self._consume(notifications, stream, turn))
        failure: frontend.Failure | None = None
        try:
            failure = await self._conversation.run_turn(text, notifications, turn.cancellation)
        finally:
            notifications.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(consumer, timeout=30)
            if not consumer.done():
                consumer.cancel()
            self._turn = None

        if turn.cancelled:
            return {"stopReason": "cancelled"}
        if failure is not None:
            raise jsonrpc.JsonRpcError(jsonrpc.INTERNAL_ERROR, failure.message)
        return {"stopReason": "end_turn"}

    async def _cancel(self) -> None:
        turn = self._turn
        if turn is None:
            return
        turn.cancelled = True
        turn.cancellation.cancel()
        await self._conversation.cancel()

    # --- what a turn reports to the client -----------------------------------

    async def _consume(
        self,
        notifications: frontend.Channel[frontend.ConversationNotification],
        stream: _Stream,
        turn: _Turn,
    ) -> None:
        while (notification := await notifications.get()) is not None:
            match notification:
                case frontend.StreamChunkReceived():
                    await self._stream(notification.message, stream)
                case frontend.MessageAppended():
                    await self._commit(notification.message, stream)
                case frontend.ToolApprovalRequested():
                    await self._ask(notification, turn)
                case _:
                    # Status labels, usage counts, steering and queued-input
                    # receipts, and cleared approvals have no protocol counterpart:
                    # an ACP client learns the turn's shape from the prompt's answer
                    # and its updates. This server never queues an input of its own,
                    # so the queued kinds are unreachable here anyway.
                    continue

    async def _stream(self, message: frontend.Message | None, stream: _Stream) -> None:
        if message is None:
            return
        thought = _delta(stream.reasoning, message.reasoning_content)
        if thought:
            stream.reasoning = message.reasoning_content
            await self._update(updates.agent_thought_chunk(thought))
        text = _delta(stream.text, message.content)
        if text:
            stream.text = message.content
            await self._update(updates.agent_message_chunk(text))

    async def _commit(self, message: frontend.Message, stream: _Stream) -> None:
        """Send what the accumulated stream had not yet sent, then its tool calls."""
        if message.role == frontend.ROLE_ASSISTANT:
            text = _delta(stream.text, message.content)
            if text:
                stream.text = message.content
                await self._update(updates.agent_message_chunk(text))
            for call in message.tool_calls:
                await self._update({"sessionUpdate": "tool_call", **updates.tool_call(call)})
            return
        if message.role == frontend.ROLE_TOOL:
            await self._update(
                {
                    "sessionUpdate": "tool_call_update",
                    **updates.tool_call_update(message.tool_call_id, status="completed", text=message.content),
                }
            )

    async def _ask(
        self,
        notification: frontend.ToolApprovalRequested,
        turn: _Turn,
    ) -> None:
        """Ask the client, and answer with what it chose — or with a refusal.

        A cancelled turn must not leave this waiting: the runtime has already
        stopped asking, so the request is raced against the cancellation.
        """
        asking = asyncio.ensure_future(
            self._connection.request(
                "session/request_permission",
                updates.permission_request(self._session_id, notification.tool_call, notification.request),
            )
        )
        cancelled = asyncio.ensure_future(turn.cancellation.wait())
        done, _pending = await asyncio.wait({asking, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if asking not in done:
            asking.cancel()
            return
        cancelled.cancel()
        try:
            answer = asking.result()
        except Exception:
            # A client that failed to answer has not approved anything.
            answer = {}
        # The id names the prompt the client just answered. A refusal means the
        # request was already answered or has ended, and there is nothing left to
        # tell the client: its permission response was for this dialog only.
        await self._conversation.approve(frontend.Decision(_decision(answer)), notification.request_id)

    async def _update(self, update: dict[str, Any]) -> None:
        await self._connection.notify("session/update", {"sessionId": self._session_id, "update": update})

    async def _send(self, message: dict[str, Any]) -> None:
        await self._connection.send(message)

    def _modes(self) -> dict[str, Any]:
        return {
            "currentModeId": self._conversation.permission_mode(),
            "availableModes": [{"id": mode, "name": name} for mode, name in MODES],
        }


def _id(request_id: object) -> int | str:
    """A request id, as JSON-RPC allows either a string or a number."""
    return request_id if isinstance(request_id, int) else str(request_id)


def _delta(previous: str, current: str) -> str:
    """The part of ``current`` that ``previous`` did not already contain.

    Empty when the message was replaced rather than extended, because sending the
    whole text again would duplicate it; the next chunk re-syncs.
    """
    if not current or current == previous:
        return ""
    if current.startswith(previous):
        return current[len(previous) :]
    return ""


def _decision(answer: dict[str, Any]) -> str:
    outcome = answer.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("outcome") != "selected":
        return str(frontend.DENY)
    option = outcome.get("optionId")
    return DECISION_BY_OPTION.get(str(option), str(frontend.DENY))


def _prompt_text(params: dict[str, Any]) -> str:
    """The prompt's text blocks, joined.

    Only text is advertised in ``promptCapabilities``, so anything else is
    ignored rather than guessed at.
    """
    prompt = params.get("prompt")
    if not isinstance(prompt, list):
        return ""
    parts: list[str] = []
    for block in prompt:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()
