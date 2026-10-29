"""The web front end: one local page over the shared frontend ports.

It is a transport, not a second adapter: the application object it drives is the same
object the terminal drives, and the values it shows are the contract's
``ConversationView`` and notification set. What is web-specific lives here — the
HTTP surface, the event stream, the static page — and nothing else does.

``serve`` is what the entry point calls; :class:`~super_agent.web.routes.Router`
is what the tests call, because routing is a pure function of a request.
"""

from __future__ import annotations

import sys

from super_agent import frontend
from super_agent.web.assets import Assets as Assets
from super_agent.web.hub import EventHub as EventHub, Subscription as Subscription
from super_agent.web.routes import Request as Request, Response as Response, Router as Router
from super_agent.web.server import EVENTS_PATH as EVENTS_PATH, Server as Server
from super_agent.web.turns import NoPendingApproval as NoPendingApproval, TurnBusy as TurnBusy, TurnRunner as TurnRunner

__all__ = [
    "EVENTS_PATH",
    "Assets",
    "EventHub",
    "NoPendingApproval",
    "Request",
    "Response",
    "Router",
    "Server",
    "Subscription",
    "TurnBusy",
    "TurnRunner",
    "new_server",
    "serve",
]


def new_server(
    frontend_ports: frontend.FrontendPorts,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> tuple[Server, EventHub, TurnRunner]:
    """Wire the hub, the turn slot, the router, and the socket."""
    hub = EventHub()
    runner = TurnRunner(frontend_ports, hub)
    return Server(Router(frontend_ports, runner, hub), host=host, port=port), hub, runner


async def serve(frontend_ports: frontend.FrontendPorts, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the interface until the process is interrupted."""
    server, hub, _runner = new_server(frontend_ports, host=host, port=port)
    await server.start()
    print(f"super-agent web interface: http://{host}:{server.port}/", file=sys.stderr, flush=True)
    try:
        await server.serve_forever()
    finally:
        hub.close()
        await server.close()
