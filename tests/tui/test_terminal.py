"""The production shell uses ordinary terminal scrollback."""

from __future__ import annotations

import io
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Sequence

import pytest
from rich.console import Console

from super_agent.tui import APPROVE_ONCE, ROLE_ASSISTANT, Message, MessageAppended, StreamChunkReceived
from super_agent.tui.terminal import TerminalApplication, _read_line  # pyright: ignore[reportPrivateUsage]
from tests.tui.fakes import ApprovalFrontendPorts, FakeFrontendPorts, new_app


def reader(values: Sequence[str]) -> Callable[[str], Awaitable[str]]:
    pending = iter(values)

    async def read(_prompt: str) -> str:
        return next(pending)

    return read


class _LiveTTY(io.StringIO):
    """A stream that claims to be a terminal, so the live prompt path is used."""

    def isatty(self) -> bool:
        return True


class _ScriptedKeyReader:
    """Feeds keystrokes to the live prompt, pausing so queued output can run."""

    def __init__(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        self.entered = 0
        self.exited = 0

    def enter(self) -> None:
        self.entered += 1

    def exit(self) -> None:
        self.exited += 1

    def ready(self) -> bool:
        return bool(self._keys)

    def read_key(self) -> str:
        # The real reader blocks on the terminal. A short pause makes the event
        # loop run the command-output task while the prompt is already on screen,
        # which is the ordering under test.
        time.sleep(0.01)
        return self._keys.pop(0) if self._keys else "ctrl+c"


def test_terminal_input_accepts_chinese_and_replaces_invalid_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin = io.TextIOWrapper(io.BytesIO("请介绍".encode() + b"\n" + "请结".encode() + b"\xe4\n"), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)

    assert _read_line("") == "请介绍"
    assert _read_line("") == "请结�"


@pytest.mark.asyncio
async def test_terminal_appends_reply_to_normal_output() -> None:
    output = io.StringIO()
    fake = FakeFrontendPorts([MessageAppended(message=Message(role=ROLE_ASSISTANT, content="native reply"))])
    program = TerminalApplication(
        new_app(fake),
        reader=reader(("hello", "/quit")),
        console=Console(file=output, force_terminal=False, width=80),
    )

    await program.run_terminal()

    assert fake.queries == ["hello"]
    assert "native reply" in output.getvalue()
    assert "\x1b[?1049h" not in output.getvalue(), "the shell never enters the alternate screen"


@pytest.mark.asyncio
async def test_terminal_streams_reply_once() -> None:
    output = io.StringIO()
    fake = FakeFrontendPorts(
        [
            StreamChunkReceived(message=Message(role=ROLE_ASSISTANT, content="你好")),
            StreamChunkReceived(message=Message(role=ROLE_ASSISTANT, content="你好，世界")),
            MessageAppended(message=Message(role=ROLE_ASSISTANT, content="你好，世界")),
        ]
    )
    program = TerminalApplication(
        new_app(fake),
        reader=reader(("介绍项目", "/quit")),
        console=Console(file=output, force_terminal=False, width=80),
    )

    await program.run_terminal()

    assert output.getvalue().count("你好，世界") == 1
    assert fake.queries == ["介绍项目"]


@pytest.mark.asyncio
async def test_terminal_reads_inline_approval() -> None:
    output = io.StringIO()
    fake = ApprovalFrontendPorts()
    program = TerminalApplication(
        new_app(fake),
        reader=reader(("run it", "1", "/quit")),
        console=Console(file=output, force_terminal=False, width=80),
    )

    await program.run_terminal()

    assert fake.decisions == [APPROVE_ONCE]
    assert "ACTION REQUIRED" in output.getvalue()


@pytest.mark.asyncio
async def test_terminal_writes_slash_command_output_to_scrollback() -> None:
    output = io.StringIO()
    program = TerminalApplication(
        new_app(FakeFrontendPorts()),
        reader=reader(("/diff", "/quit")),
        console=Console(file=output, force_terminal=False, width=80),
    )

    await program.run_terminal()

    rendered = output.getvalue()
    assert "diff" in rendered
    assert "\x1b[?1049h" not in rendered


@pytest.mark.asyncio
async def test_terminal_help_is_inline() -> None:
    output = io.StringIO()
    program = TerminalApplication(
        new_app(FakeFrontendPorts()),
        reader=reader(("/help", "/quit")),
        console=Console(file=output, force_terminal=False, width=80),
    )

    await program.run_terminal()

    assert "Slash commands start with /" in output.getvalue()


@pytest.mark.asyncio
async def test_terminal_restores_the_prompt_after_command_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command that prints a notice must not leave the prompt overwritten.

    The notice is printed from a task, after the live prompt has been drawn. The
    shell has to take the prompt down and put it back; otherwise the notice lands
    on the prompt line and typing continues on an invisible prompt.
    """
    stdout = _LiveTTY()
    monkeypatch.setattr(sys, "stdin", _LiveTTY())
    monkeypatch.setattr(sys, "stdout", stdout)
    keys = [*"/clear", "enter", *"/quit", "enter"]
    program = TerminalApplication(
        new_app(FakeFrontendPorts()),
        console=Console(file=stdout, force_terminal=False, width=80),
        key_reader=_ScriptedKeyReader(keys),
    )

    await program.run_terminal()

    rendered = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", stdout.getvalue())
    assert "New conversation" in rendered
    assert re.search(r"New conversation[^\n]*\n\u276f ", rendered), rendered


@pytest.mark.skipif(sys.platform == "win32", reason="SIGWINCH is POSIX-only")
@pytest.mark.asyncio
async def test_resize_signal_relayouts_the_live_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live resize must reach the app instead of waiting for a restart.

    The shell reads the terminal size once at startup. Without a ``SIGWINCH``
    handler the transcript and palette keep the old width; this sends the real
    signal and asserts the app took the new size.
    """
    stdout = _LiveTTY()
    monkeypatch.setattr(sys, "stdin", _LiveTTY())
    monkeypatch.setattr(sys, "stdout", stdout)
    sizes = iter([os.terminal_size((100, 30)), os.terminal_size((40, 12))])

    def terminal_size(fallback: tuple[int, int]) -> os.terminal_size:
        return next(sizes, os.terminal_size((40, 12)))

    monkeypatch.setattr(shutil, "get_terminal_size", terminal_size)
    program = TerminalApplication(
        new_app(FakeFrontendPorts()),
        console=Console(file=stdout, force_terminal=False, width=80),
        key_reader=_ScriptedKeyReader([""] * 50 + ["ctrl+c"]),
    )

    def resize_later() -> None:
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGWINCH)

    thread = threading.Thread(target=resize_later, daemon=True)
    thread.start()
    try:
        await program.run_terminal()
    finally:
        thread.join(timeout=2)

    assert (program.model.width, program.model.height) == (40, 12)
