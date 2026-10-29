"""The HTTP surface, as a pure function of a request.

Every route answers with the contract's own values, encoded by
:mod:`super_agent.frontend.wire`. Nothing here knows a socket, a header spelling,
or a runtime type, which is what lets the whole surface be tested by calling
:meth:`Router.handle` and reading the response.

The one exception is the event stream: it is a subscription, not a response,
because it never ends on its own. The server owns the framing; the router owns
what a subscriber is greeted with.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.parse
from typing import Any, cast

from super_agent import frontend
from super_agent.frontend import wire
from super_agent.web.hub import EventHub, Subscription
from super_agent.web.turns import NoPendingApproval, TurnBusy, TurnRunner

__all__ = ["Request", "Response", "Router", "json_response"]


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    """One parsed request. The body is raw bytes; :attr:`json` decodes it."""

    method: str
    path: str
    body: bytes = b""
    query: dict[str, list[str]] = dataclasses.field(default_factory=dict[str, list[str]])

    @property
    def json(self) -> dict[str, Any]:
        """The body as a JSON object, or an empty mapping when it is not one."""
        if not self.body:
            return {}
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {}
        return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}


@dataclasses.dataclass(frozen=True, slots=True)
class Response:
    """One response. ``content_type`` is empty for a body that has none."""

    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


def json_response(payload: object, status: int = 200) -> Response:
    return Response(status=status, body=json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def string_list(value: object) -> list[str]:
    """The value when it is a list of strings, refusing anything else."""
    if not isinstance(value, list):
        raise ValueError("args must be a list of strings")
    items: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            raise ValueError("args must be a list of strings")
        items.append(item)
    return items


def error_response(status: int, message: str) -> Response:
    return json_response({"error": message}, status=status)


class Router:
    """The route table, over the port and the turn slot."""

    __slots__ = ("_frontend_ports", "_hub", "_runner")

    def __init__(self, frontend_ports: frontend.FrontendPorts, runner: TurnRunner, hub: EventHub) -> None:
        self._frontend_ports = frontend_ports
        self._runner = runner
        self._hub = hub

    def subscribe(self) -> Subscription:
        """Attach an event stream, greeted with the state a fresh tab needs."""
        return self._hub.subscribe(greeting=self._runner.snapshot_event())

    async def handle(self, request: Request) -> Response:
        """Dispatch one request. Unexpected failures become a 500 with the reason."""
        try:
            return await self._dispatch(request)
        except (TurnBusy, NoPendingApproval) as conflict:
            return error_response(409, str(conflict))
        except (ValueError, KeyError) as invalid:
            return error_response(400, str(invalid))
        except Exception as failure:
            return error_response(500, wire.error_text(failure))

    async def _dispatch(self, request: Request) -> Response:
        method = request.method.upper()
        parts = [urllib.parse.unquote(part) for part in request.path.strip("/").split("/") if part]
        if not parts or parts[0] != "api":
            return error_response(404, "not found")

        match (method, parts[1:]):
            case ("GET", ["health"]):
                return json_response(
                    {
                        "ok": True,
                        "running": self._runner.running,
                        "subscribers": self._hub.subscribers,
                    }
                )
            case ("GET", ["snapshot"]):
                return json_response(
                    {
                        "snapshot": wire.view_to_json(self._frontend_ports.snapshot()),
                        "config": self._config(),
                        "running": self._runner.running,
                    }
                )
            case ("GET", ["config"]):
                return json_response(self._config())
            case ("GET", ["instructions"]):
                return json_response({"sources": list(self._frontend_ports.config_view().instruction_sources)})
            case ("POST", ["turns"]):
                text = self._text(request)
                await self._runner.start_turn(text)
                return json_response({"accepted": True}, status=202)
            case ("POST", ["steering"]):
                receipt = await self._runner.steer(self._text(request))
                return json_response(wire.receipt_to_json(receipt))
            case ("POST", ["queue"]):
                receipt = await self._runner.queue(self._text(request))
                return json_response(wire.receipt_to_json(receipt))
            case ("POST", ["cancel"]):
                await self._runner.cancel()
                return json_response({"ok": True})
            case ("POST", ["approvals"]):
                await self._runner.approve(
                    str(request.json.get("decision", "")),
                    str(request.json.get("request_id", "")),
                )
                return json_response({"ok": True})
            case ("POST", ["permission-mode"]):
                await self._frontend_ports.set_permission_mode(str(request.json.get("mode", "")))
                return json_response(self._config())
            case ("GET", ["providers"]):
                return json_response(
                    {"providers": [self._provider(item) for item in self._frontend_ports.list_providers()]}
                )
            case ("POST", ["providers", provider_name]):
                api_key = str(request.json.get("api_key", ""))
                model = str(request.json.get("model", ""))
                if not api_key.strip():
                    raise ValueError("api_key is required")
                await self._frontend_ports.configure_provider(provider_name, api_key, model)
                return json_response(self._config())
            case ("GET", ["memory"]):
                return json_response(await self._memory())
            case ("POST", ["memory"]):
                enabled = request.json.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be a boolean")
                await self._frontend_ports.set_memory_enabled(enabled)
                return json_response(await self._memory())
            case ("GET", ["sessions"]):
                sessions = await self._frontend_ports.list_sessions()
                return json_response({"sessions": [self._session(item) for item in sessions]})
            case ("POST", ["sessions", session_id, "resume"]):
                await self._frontend_ports.resume(session_id)
                self._hub.publish(self._runner.snapshot_event())
                return json_response({"ok": True})
            case ("POST", ["sessions", session_id, "rename"]):
                await self._frontend_ports.rename_session(session_id, str(request.json.get("title", "")))
                return json_response({"ok": True})
            case ("DELETE", ["sessions", session_id]):
                await self._frontend_ports.delete_session(session_id)
                return json_response({"ok": True})
            case ("POST", ["reset"]):
                await self._frontend_ports.reset()
                self._hub.publish(self._runner.snapshot_event())
                return json_response({"ok": True})
            case ("POST", ["undo"]):
                await self._frontend_ports.undo()
                self._hub.publish(self._runner.snapshot_event())
                return json_response({"ok": True})
            case ("POST", ["workflows", name]):
                prompt = frontend.WORKFLOW_PROMPTS.get(name)
                if prompt is None:
                    raise ValueError(f"unknown workflow: {name}")
                await self._runner.start_turn(prompt)
                return json_response({"accepted": True}, status=202)
            case ("GET", ["mcp"]):
                return json_response({"servers": [self._mcp(item) for item in self._frontend_ports.list_mcp_servers()]})
            case ("POST", ["mcp"]):
                name = str(request.json.get("name", "")).strip()
                command = str(request.json.get("command", "")).strip()
                args = request.json.get("args")
                if not name or not command:
                    raise ValueError("name and command are required")
                if args is None:
                    args = []
                await self._frontend_ports.add_mcp_server(name, command, string_list(cast("object", args)))
                return json_response({"ok": True})
            case ("DELETE", ["mcp", name]):
                await self._frontend_ports.remove_mcp_server(name)
                return json_response({"ok": True})
            case ("POST", ["mcp", name, "restart"]):
                await self._frontend_ports.restart_mcp_server(name)
                return json_response({"ok": True})
            case ("GET", ["attachments"]):
                return json_response(
                    {"items": [self._attachment(item) for item in await self._frontend_ports.pending_attachments()]}
                )
            case ("POST", ["attachments"]):
                path = str(request.json.get("path", "")).strip()
                if not path:
                    raise ValueError("path is required")
                return json_response(self._attachment(await self._frontend_ports.attach(path)))
            case ("GET", ["workspace", "diff"]):
                return json_response({"diff": await self._frontend_ports.git_diff()})
            case ("GET", ["workspace", "status"]):
                return json_response({"status": await self._frontend_ports.git_status()})
            case ("GET", ["workspace", "diagnostics"]):
                path = (request.query.get("path") or [""])[0].strip()
                if not path:
                    raise ValueError("path is required")
                return json_response({"diagnostics": await self._frontend_ports.diagnostics(path)})
            case ("GET", ["extensions"]):
                return json_response(
                    {
                        "commands": self._frontend_ports.custom_commands(),
                        "skills": self._frontend_ports.skills(),
                        "plugins": self._frontend_ports.plugins(),
                    }
                )
            case ("POST", ["extensions", "expand"]):
                name = str(request.json.get("name", "")).strip()
                arguments = str(request.json.get("arguments", ""))
                if not name:
                    raise ValueError("name is required")
                return json_response({"text": await self._frontend_ports.expand_custom_command(name, arguments)})
            case ("POST", ["memory", "items"]):
                text = str(request.json.get("text", "")).strip()
                if not text:
                    raise ValueError("text is required")
                await self._frontend_ports.remember(text)
                return json_response(await self._memory())
            case ("DELETE", ["memory", "items"]):
                await self._frontend_ports.forget_memories()
                return json_response(await self._memory())
            case ("GET", ["agents"]):
                return json_response(
                    {
                        "agents": [self._agent(item) for item in self._frontend_ports.list_agents()],
                        "current": self._agent(self._frontend_ports.current_agent()),
                    }
                )
            case ("POST", ["agents", name]):
                await self._frontend_ports.use_agent(name)
                return json_response(self._config())
            case ("POST", ["sessions", session_id, "compact"]):
                self._require_current(session_id)
                await self._frontend_ports.compact(str(request.json.get("summary", "")))
                self._hub.publish(self._runner.snapshot_event())
                return json_response({"ok": True})
            case ("POST", ["sessions", session_id, "fork"]):
                self._require_current(session_id)
                return json_response({"id": await self._frontend_ports.fork(str(request.json.get("title", "")))})
            case ("POST", ["sessions", session_id, "export"]):
                self._require_current(session_id)
                export_format = str(request.json.get("format", "markdown")).strip()
                return json_response({"path": await self._frontend_ports.export(export_format)})
            case _:
                return error_response(404, f"no route for {method} {request.path}")

    def _config(self) -> dict[str, Any]:
        """What the composer's status bar shows, read back from the application.

        The value is the contract's :class:`~super_agent.frontend.ports.ConfigView`,
        not a mapping assembled here: identity, policy and capabilities have one
        definition, and a transport that re-invented the shape would drift from the
        terminal that shows the same session.
        """
        return wire.config_to_json(self._frontend_ports.config_view())

    @staticmethod
    def _provider(item: frontend.ProviderView) -> dict[str, Any]:
        return {"name": item.name, "model": item.model, "base_url": item.base_url, "has_key": item.has_key}

    async def _memory(self) -> dict[str, Any]:
        """The cross-session memory's state and its lines.

        Both come from the application, so the browser shows the switch it would
        actually get rather than one it hopes for.
        """
        return {
            "enabled": self._frontend_ports.memory_enabled(),
            "backend": self._frontend_ports.memory_backend(),
            "items": await self._frontend_ports.memories(),
        }

    @staticmethod
    def _session(item: frontend.SessionSummary) -> dict[str, Any]:
        return {
            "id": item.id,
            "title": item.title,
            "provider": item.provider,
            "model": item.model,
            "cwd": item.cwd,
            "parent_id": item.parent_id,
        }

    @staticmethod
    def _mcp(item: frontend.MCPServerSummary) -> dict[str, Any]:
        return {"name": item.name, "tools": list(item.tools)}

    @staticmethod
    def _attachment(item: frontend.AttachmentSummary) -> dict[str, Any]:
        return {"name": item.name, "mime": item.mime}

    @staticmethod
    def _agent(item: frontend.AgentSummary) -> dict[str, Any]:
        return {
            "name": item.name,
            "provider": item.provider,
            "model": item.model,
            "permission_mode": item.permission_mode,
        }

    def _require_current(self, session_id: str) -> None:
        """Refuse a session-scoped command aimed at a session that is not active."""
        current = self._frontend_ports.config_view().session_id
        if session_id != current:
            raise ValueError("session id does not match the active session")

    @staticmethod
    def _text(request: Request) -> str:
        """The message text, refusing an empty one.

        An empty turn would spend a model call to say nothing, so it is a client
        error rather than a turn that quietly does nothing.
        """
        text = str(request.json.get("text", ""))
        if not text.strip():
            raise ValueError("text is required")
        return text
