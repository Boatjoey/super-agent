"""The POSIX key reader, driven through real file descriptors.

``terminal_io`` is the only place the terminal front end talks to ``termios`` and
``select``; the smoke test drives a pseudo-terminal end to end but says nothing
about the individual byte sequences. These tests pin the canonical key names and
the UTF-8 decoding, including the end-of-input cases.
"""

from __future__ import annotations

import os
import pty
import sys
import termios
import types

import pytest

from super_agent.tui.terminal_io import PosixKeyReader

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PosixKeyReader is the POSIX implementation")


def reader_over_pipe(monkeypatch: pytest.MonkeyPatch) -> tuple[PosixKeyReader, int, int]:
    """A reader whose stdin is a pipe, plus the read and write ends."""
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(fileno=lambda: read_fd))
    return PosixKeyReader(), read_fd, write_fd


@pytest.mark.parametrize(
    ("payload", "key"),
    [
        (b"\r", "enter"),
        (b"\n", "enter"),
        (b"\t", "tab"),
        (b"\x7f", "backspace"),
        (b"\x08", "backspace"),
        (b"\x03", "ctrl+c"),
        (b"\x04", "ctrl+d"),
        (b"\x15", "ctrl+u"),
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[C", "right"),
        (b"\x1b[D", "left"),
        (b"\x1b", "esc"),
    ],
)
def test_single_keys_decode_to_canonical_names(monkeypatch: pytest.MonkeyPatch, payload: bytes, key: str) -> None:
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    try:
        os.write(write_fd, payload)
        assert reader.read_key() == key
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_multibyte_character_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    try:
        os.write(write_fd, "好".encode())
        assert reader.read_key() == "好"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_character_split_across_reads_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    data = "好".encode()
    try:
        os.write(write_fd, data[:1])
        os.write(write_fd, data[1:])
        assert reader.read_key() == "好"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_no_pending_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    try:
        assert reader.read_key() == ""
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_eof_returns_ctrl_d(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    try:
        os.close(write_fd)
        assert reader.read_key() == "ctrl+d"
    finally:
        os.close(read_fd)


def test_eof_inside_a_multibyte_character_ends_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A truncated character must end input, not spin on the empty read."""
    reader, read_fd, write_fd = reader_over_pipe(monkeypatch)
    try:
        os.write(write_fd, "好".encode()[:1])
        os.close(write_fd)
        assert reader.read_key() == "ctrl+d"
    finally:
        os.close(read_fd)


def test_enter_and_exit_restore_the_terminal_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    master, slave = pty.openpty()
    try:
        monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(fileno=lambda: slave))
        reader = PosixKeyReader()
        original = termios.tcgetattr(slave)

        reader.enter()
        during = termios.tcgetattr(slave)
        assert not during[3] & termios.ICANON, "cbreak leaves the terminal in canonical mode"
        assert not during[3] & termios.ECHO, "cbreak leaves keystrokes echoed"

        reader.exit()
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)
