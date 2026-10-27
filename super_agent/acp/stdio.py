"""The stdio transport: one JSON object per line, in both directions.

This is the framing the Agent Client Protocol uses when an editor launches the
agent as a child process. Reading happens on a worker thread because ``readline``
blocks; writing stays on the loop, so messages keep their order.

Nothing but protocol traffic may go to stdout: a stray ``print`` would be read as a
message. Anything a human needs to see goes to stderr.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import IO, Any

from super_agent import frontend
from super_agent.acp import jsonrpc
from super_agent.acp.agent import AcpAgent
from super_agent.acp.connection import Connection

__all__ = ["run", "serve_streams"]


async def serve_streams(
    conversation: frontend.Conversation,
    *,
    session_id: str,
    cwd: str = "",
    stdin: IO[bytes] | None = None,
    stdout: IO[str] | None = None,
) -> None:
    """Serve the protocol on the given streams until input ends."""
    reader = stdin if stdin is not None else sys.stdin.buffer
    writer = stdout if stdout is not None else sys.stdout

    async def send(message: dict[str, Any]) -> None:
        writer.write(json.dumps(message, ensure_ascii=False) + "\n")
        writer.flush()

    agent = AcpAgent(conversation, Connection(send), session_id=session_id, cwd=cwd)
    try:
        while True:
            line = await asyncio.to_thread(reader.readline)
            if not line:
                return
            text = line.decode("utf-8", "replace").strip() if isinstance(line, bytes) else str(line).strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except ValueError:
                await send(jsonrpc.error(None, jsonrpc.PARSE_ERROR, "invalid JSON"))
                continue
            if not isinstance(message, dict):
                await send(jsonrpc.error(None, jsonrpc.INVALID_REQUEST, "expected a JSON object"))
                continue
            await agent.handle(message)
    finally:
        await agent.shut_down()


def run(conversation: frontend.Conversation, *, session_id: str, cwd: str = "") -> int:
    """Serve on the process's own stdin and stdout.

    A clean end of input is a clean exit: the editor closed the pipe, which is how
    an ACP session ends.
    """
    try:
        asyncio.run(serve_streams(conversation, session_id=session_id, cwd=cwd))
    except KeyboardInterrupt:
        return 0
    return 0
