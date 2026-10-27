"""The ACP front end: an editor drives the same conversation the terminal does.

The Agent Client Protocol is JSON-RPC 2.0 on stdio. This package turns it into
calls on the shared contract, and turns what the contract reports into
``session/update`` notifications and ``session/request_permission`` requests.

Nothing here knows about the runtime, the terminal, or HTTP. It is the third
adapter on the same port, and the only one whose client is another program.
"""

from __future__ import annotations

from super_agent.acp.agent import MODES as MODES, PROTOCOL_VERSION as PROTOCOL_VERSION, AcpAgent as AcpAgent
from super_agent.acp.connection import Connection as Connection
from super_agent.acp.stdio import run as run, serve_streams as serve_streams

__all__ = ["MODES", "PROTOCOL_VERSION", "AcpAgent", "Connection", "run", "serve_streams"]
