"""Which front end runs when no flag names one.

Windows ships without the terminal, so naming no flag must open the web interface
there, while POSIX platforms keep the terminal as the default. The explicit web
flag is unaffected by the platform.
"""

from __future__ import annotations

from super_agent import __main__
from super_agent.app import Flags


def test_windows_defaults_to_the_web_interface() -> None:
    assert __main__.select_front_end(Flags(), "win32") == "web"


def test_windows_keeps_the_explicit_web_flag() -> None:
    assert __main__.select_front_end(Flags(web=True), "win32") == "web"


def test_posix_defaults_to_the_terminal() -> None:
    assert __main__.select_front_end(Flags(), "linux") == "terminal"
    assert __main__.select_front_end(Flags(), "darwin") == "terminal"


def test_posix_keeps_the_explicit_web_front_end() -> None:
    assert __main__.select_front_end(Flags(web=True), "linux") == "web"
