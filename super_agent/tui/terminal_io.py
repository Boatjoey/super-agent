"""Platform-specific terminal I/O, behind one interface.

The interactive prompt needs three things the two major platforms provide
differently: a cbreak-style mode that returns each keystroke without waiting for
a newline and without echoing, a non-blocking "is a key ready" probe, and a
blocking "read one key" call that reports arrow keys and control keys in one
canonical vocabulary.

POSIX does this with ``termios``/``tty`` and ``select`` on the stdin file
descriptor; Windows does it with ``msvcrt``. This module hides that split behind
:class:`KeyReader`, so the terminal shell has no platform branch of its own and
``import super_agent.tui`` no longer fails on Windows by importing ``termios``.

The key names are the contract in :class:`super_agent.tui.runtime.KeyMsg`:
printable keys come through as a single character, and special keys are named
``enter``, ``tab``, ``esc``, ``up``, ``down``, ``left``, ``right``, ``backspace``,
``ctrl+c``, ``ctrl+d``, ``ctrl+u``.
"""

from __future__ import annotations

import codecs
import os
import select
import sys
from typing import Protocol

__all__ = ["KeyReader", "new_key_reader"]


class KeyReader(Protocol):
    """Reads single keystrokes in canonical names, between cbreak and normal mode."""

    def enter(self) -> None:
        """Switch the terminal to cbreak: per-keystroke, no echo."""

    def exit(self) -> None:
        """Restore the terminal's original mode."""

    def ready(self) -> bool:
        """Whether a keystroke is already buffered."""

    def read_key(self) -> str:
        """Block until one keystroke arrives and return its canonical name."""


#: The arrow-key escape sequences, by the bytes a terminal sends.
_ARROWS = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
}

#: The single-byte control keys, by byte.
_CONTROLS = {
    b"\r": "enter",
    b"\n": "enter",
    b"\t": "tab",
    b"\x7f": "backspace",
    b"\x08": "backspace",
    b"\x03": "ctrl+c",
    b"\x04": "ctrl+d",
    b"\x15": "ctrl+u",
}


class PosixKeyReader:
    """termios/select-based reader, the Unix implementation."""

    __slots__ = ("_fd", "_original")

    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self._original: object | None = None

    def enter(self) -> None:
        import termios
        import tty

        self._original = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        settings = termios.tcgetattr(self._fd)
        settings[3] &= ~termios.ECHO
        termios.tcsetattr(self._fd, termios.TCSADRAIN, settings)

    def exit(self) -> None:
        import termios

        if self._original is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original)
            self._original = None

    def ready(self) -> bool:
        return bool(select.select([self._fd], [], [], 0.0)[0])

    def read_key(self) -> str:
        fd = self._fd
        if not select.select([fd], [], [], 0.1)[0]:
            return ""
        first = os.read(fd, 1)
        if not first:
            return "ctrl+d"
        if first == b"\x1b":
            sequence = bytearray(first)
            while len(sequence) < 3 and select.select([fd], [], [], 0.03)[0]:
                sequence.extend(os.read(fd, 1))
            return _ARROWS.get(bytes(sequence), "esc")
        control = _CONTROLS.get(first)
        if control is not None:
            return control
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        character = decoder.decode(first)
        while not character:
            character = decoder.decode(os.read(fd, 1))
        return character


class WindowsKeyReader:
    """msvcrt-based reader, the Windows implementation.

    ``getwch`` returns Unicode characters and the arrow keys' second half as a
    ``0x0000``/``0xE0`` lead byte followed by the direction byte, which is how a
    Windows console reports function and arrow keys. Ordinary printable keys come
    straight through; control keys are mapped by their byte value.
    """

    __slots__ = ()

    def enter(self) -> None:
        # The console already reads one character at a time via msvcrt; there is no
        # termios mode to switch. A no-op keeps the two readers symmetric.
        return

    def exit(self) -> None:
        # Nothing to restore.
        return

    def ready(self) -> bool:
        import msvcrt

        return bool(msvcrt.kbhit())

    def read_key(self) -> str:
        import msvcrt

        while not msvcrt.kbhit():
            # msvcrt has no blocking "wait for a key" that also participates in the
            # event loop; the caller awaits this on a worker thread, so a short poll
            # is how it waits without spinning the CPU.
            import time

            time.sleep(0.02)
        first = msvcrt.getwch()
        if first in ("\x00", "\xe0"):
            # A function/arrow key: the lead byte followed by the direction code.
            second = msvcrt.getwch()
            return {
                "H": "up",
                "P": "down",
                "M": "right",
                "K": "left",
            }.get(second, "esc")
        if first == "\x1b":
            return "esc"
        if first in ("\r", "\n"):
            return "enter"
        if first == "\t":
            return "tab"
        if first in ("\x7f", "\x08"):
            return "backspace"
        if first == "\x03":
            return "ctrl+c"
        if first == "\x04":
            return "ctrl+d"
        if first == "\x15":
            return "ctrl+u"
        return first


def new_key_reader() -> KeyReader:
    """The reader for this platform."""
    if sys.platform == "win32":
        return WindowsKeyReader()
    return PosixKeyReader()
