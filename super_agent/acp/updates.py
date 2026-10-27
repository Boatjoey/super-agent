"""The ACP payloads, built from the front-end contract's values.

Two vocabularies meet here: the contract's (a message, a tool call, a permission
request) and the protocol's (``session/update`` variants, ``tool_call`` kinds). The
translation is exhaustive by construction — a kind the protocol does not name
becomes ``other`` rather than an invented one.
"""

from __future__ import annotations

import json
from typing import Any

from super_agent import frontend

__all__ = [
    "agent_message_chunk",
    "agent_thought_chunk",
    "available_commands_update",
    "message_chunks",
    "permission_options",
    "permission_request",
    "tool_call",
    "tool_call_update",
    "tool_kind",
    "tool_title",
]

#: The ACP tool kinds, by the tool name this agent ships. A name that is not
#: listed is ``other``: the client then shows a generic card, which is honest.
TOOL_KINDS: dict[str, str] = {
    "read_file": "read",
    "list_files": "read",
    "write_file": "edit",
    "apply_patch": "edit",
    "run_command": "execute",
    "bash": "execute",
    "git_status": "execute",
    "git_diff": "execute",
    "search": "search",
    "web_search": "search",
    "browser_fetch": "fetch",
    "delegate": "other",
}

#: The three options a permission request offers, in the order a client shows
#: them. ``allow_always`` is the runtime's "always" answer, which the session
#: remembers for the rest of the turn.
PERMISSION_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("allow_once", "Allow once", "allow_once"),
    ("allow_always", "Always allow", "allow_always"),
    ("reject_once", "Reject", "reject_once"),
)

#: The protocol's answer for each offered option.
DECISION_BY_OPTION: dict[str, str] = {
    "allow_once": str(frontend.APPROVE_ONCE),
    "allow_always": str(frontend.APPROVE_ALWAYS),
    "reject_once": str(frontend.DENY),
    "reject_always": str(frontend.DENY),
}


def tool_kind(name: str) -> str:
    return TOOL_KINDS.get(name, "other")


def tool_title(call: frontend.ToolCall) -> str:
    """A one-line title: the tool, then the most telling argument.

    A card that says only ``run_command`` makes the user approve blind, so the
    argument comes with it.
    """
    detail = _argument_summary(call.input)
    return f"{call.name} {detail}".strip() if detail else call.name


def tool_call(call: frontend.ToolCall, *, status: str = "pending") -> dict[str, Any]:
    return {
        "toolCallId": call.id,
        "title": tool_title(call),
        "kind": tool_kind(call.name),
        "status": status,
        "rawInput": _argument_object(call.input),
    }


def tool_call_update(call_id: str, *, status: str, text: str = "") -> dict[str, Any]:
    update: dict[str, Any] = {"toolCallId": call_id, "status": status}
    if text:
        update["content"] = [{"type": "content", "content": {"type": "text", "text": text}}]
    return update


def agent_message_chunk(text: str) -> dict[str, Any]:
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}


def agent_thought_chunk(text: str) -> dict[str, Any]:
    return {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": text}}


def available_commands_update(names: tuple[str, ...]) -> dict[str, Any]:
    return {
        "sessionUpdate": "available_commands_update",
        "availableCommands": [{"name": name, "description": f"/{name}", "input": None} for name in names if name],
    }


def permission_options() -> list[dict[str, Any]]:
    return [{"optionId": option, "name": name, "kind": kind} for option, name, kind in PERMISSION_OPTIONS]


def permission_request(session_id: str, call: frontend.ToolCall, request: frontend.PermissionRequest) -> dict[str, Any]:
    tool = tool_call(call, status="pending")
    if request.reason:
        tool["title"] = f"{tool['title']} — {request.reason}"
    return {"sessionId": session_id, "toolCall": tool, "options": permission_options()}


def message_chunks(message: frontend.Message) -> list[dict[str, Any]]:
    """Every update needed to replay one committed message.

    Used by ``session/load``: a client that attaches to a saved session must see
    the transcript it missed, expressed as the same chunks a live turn produces.
    """
    updates: list[dict[str, Any]] = []
    if message.reasoning_content:
        updates.append(agent_thought_chunk(message.reasoning_content))
    if message.role == frontend.ROLE_USER:
        if message.content:
            updates.append(
                {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": message.content}}
            )
        return updates
    if message.content:
        updates.append(agent_message_chunk(message.content))
    for call in message.tool_calls:
        updates.append({"sessionUpdate": "tool_call", **tool_call(call)})
    return updates


def _argument_object(input_text: str) -> Any:
    """The call's arguments, as JSON when they are JSON and as text otherwise."""
    if not input_text:
        return {}
    try:
        return json.loads(input_text)
    except (ValueError, TypeError):
        return {"raw": input_text}


def _argument_summary(input_text: str) -> str:
    """The argument a card should show first, or a truncated form of all of them."""
    parsed = _argument_object(input_text)
    if isinstance(parsed, dict):
        for key in ("command", "path", "query", "url", "pattern"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value if len(value) <= 120 else value[:117] + "…"
        text = json.dumps(parsed, ensure_ascii=False)
    else:
        text = str(parsed)
    return text if len(text) <= 120 else text[:117] + "…"
