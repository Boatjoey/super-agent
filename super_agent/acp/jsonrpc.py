"""JSON-RPC 2.0, as the Agent Client Protocol frames it.

One object per line on stdio, which is why nothing here deals with lengths or
headers: the newline is the frame. The error codes are the ones the specification
names, so a client can tell "that method does not exist" from "your parameters are
wrong" without reading a message string.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "JsonRpcError",
    "error",
    "is_response",
    "notification",
    "request",
    "result",
]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """A failure that becomes an error response rather than a dropped message."""

    __slots__ = ("code", "message")

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def request(request_id: int | str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def result(request_id: int | str, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id: int | str | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def is_response(message: dict[str, Any]) -> bool:
    """Whether this message answers a request we sent, rather than asking one.

    A response carries no ``method``. Testing for ``id`` alone would misread a
    client request as an answer to a request that does not exist.
    """
    return "method" not in message and ("result" in message or "error" in message)
