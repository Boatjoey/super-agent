"""The web front end: one local page over the shared frontend ports.

It is a front-end adapter, not a second application: the application object it drives
is the same object the terminal drives, and the values it shows are the contract's
``ConversationView`` and notification set. What is web-specific lives here — the
HTTP surface, the event stream, the static page — and nothing else does.

``serve`` is what the entry point calls; :class:`~super_agent.web.routes.Router`
is what the tests call, because routing is a pure function of a request. Before
any request reaches the router, :class:`~super_agent.web.access.WebAccess` checks
that it names this server, was not sent by another site, and carries the cookie
the launch token was exchanged for.
"""

from __future__ import annotations

import sys

from super_agent import frontend
from super_agent.web.access import WebAccess as WebAccess
from super_agent.web.assets import Assets as Assets
from super_agent.web.hub import EventHub as EventHub, Subscription as Subscription
from super_agent.web.routes import Request as Request, Response as Response, Router as Router
from super_agent.web.server import EVENTS_PATH as EVENTS_PATH, WebAdapter as WebAdapter
from super_agent.web.turns import NoPendingApproval as NoPendingApproval, TurnBusy as TurnBusy, TurnRunner as TurnRunner

__all__ = [
    "EVENTS_PATH",
    "Assets",
    "EventHub",
    "NoPendingApproval",
    "Request",
    "Response",
    "Router",
    "Subscription",
    "TurnBusy",
    "TurnRunner",
    "WebAccess",
    "WebAdapter",
    "new_web_adapter",
    "serve",
]


def new_web_adapter(
    frontend_ports: frontend.FrontendPorts,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> tuple[WebAdapter, EventHub, TurnRunner]:
    """Wire the hub, the turn slot, the router, and the socket."""
    hub = EventHub()
    runner = TurnRunner(frontend_ports, hub)
    return WebAdapter(Router(frontend_ports, runner, hub), host=host, port=port), hub, runner


async def serve(frontend_ports: frontend.FrontendPorts, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the interface until the process is interrupted.

    The address line is the only place the launch token is ever written: the
    operator who started the process reads it there and opens it once.
    """
    server, hub, _runner = new_web_adapter(frontend_ports, host=host, port=port)
    await server.start()
    print(f"super-agent web interface: {server.address}", file=sys.stderr, flush=True)
    try:
        await server.serve_forever()
    finally:
        hub.close()
        await server.close()
