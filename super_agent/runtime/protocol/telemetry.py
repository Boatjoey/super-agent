"""Outbound telemetry contract."""

from collections.abc import Mapping
from typing import Any, Protocol

type Fields = Mapping[str, Any]


class Recorder(Protocol):
    def record(self, kind: str, fields: Fields) -> None: ...


_recorder: Recorder | None = None


def install(recorder: Recorder | None) -> None:
    global _recorder
    _recorder = recorder


def record(kind: str, fields: Fields) -> None:
    if _recorder is not None:
        _recorder.record(kind, fields)
