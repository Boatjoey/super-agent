"""Only the web front end draws a launch token; the terminal never meets the web adapter.

The entry point builds the session once and hands it to one front end. These tests
stand in for the session and both front ends, so what they prove is the routing:
the terminal path runs without the web interface, its token or its address line,
and the web path is the only one that serves.
"""

from __future__ import annotations

import types
from typing import Any, cast

import pytest

from super_agent import __main__, app, frontend
from tests.fakes.frontend import FakeFrontendPorts


class StandInSession:
    """Just enough of a session for :func:`super_agent.__main__.run` to close it."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def stand_in(monkeypatch: pytest.MonkeyPatch) -> tuple[StandInSession, dict[str, list[Any]]]:
    """Replace the session factory and both front ends, recording which ran."""
    session = StandInSession()
    calls: dict[str, list[Any]] = {"terminal": [], "web": []}

    async def new_session(_cfg: object) -> tuple[StandInSession, None, None, None]:
        return session, None, None, None

    async def run_terminal(*arguments: object) -> None:
        calls["terminal"].append(arguments)

    async def serve(frontend_ports: frontend.FrontendPorts, *, host: str, port: int) -> None:
        calls["web"].append((frontend_ports, host, port))

    def new_application(*_arguments: object, **_options: object) -> FakeFrontendPorts:
        return FakeFrontendPorts()

    real_select = __main__.select_front_end

    def select_on_posix(flags: app.Flags, _platform: str) -> str:
        # Pin the platform to a POSIX one, where both front ends exist; the
        # platform rule itself is covered by tests/app/test_front_end_selection.py.
        return real_select(flags, "linux")

    monkeypatch.setattr(app, "new_session_with_extensions", new_session)
    monkeypatch.setattr(__main__, "new_agent_application", new_application)
    monkeypatch.setattr(__main__, "_run_terminal", run_terminal)
    monkeypatch.setattr(__main__.web, "serve", serve)
    monkeypatch.setattr(__main__, "select_front_end", select_on_posix)
    return session, calls


def config() -> app.Config:
    stand_in_config = types.SimpleNamespace(
        sandbox_downgraded=False,
        workspace=None,
        project=types.SimpleNamespace(root="/project"),
    )
    return cast("app.Config", stand_in_config)


@pytest.mark.asyncio
async def test_the_terminal_front_end_never_starts_the_web_interface(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session, calls = stand_in(monkeypatch)

    status = await __main__.run(config(), app.Flags())

    assert status == 0
    assert len(calls["terminal"]) == 1
    assert calls["web"] == []
    assert session.closed
    output = capsys.readouterr()
    assert "token" not in output.err + output.out
    assert "web interface" not in output.err + output.out


@pytest.mark.asyncio
async def test_the_web_flag_is_the_only_way_to_the_web_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    _session, calls = stand_in(monkeypatch)

    status = await __main__.run(config(), app.Flags(web=True, host="192.0.2.10"), port=0)

    assert status == 0
    assert calls["terminal"] == []
    assert [(host, port) for _ports, host, port in calls["web"]] == [("192.0.2.10", 0)]
