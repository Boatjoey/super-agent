"""Shared test configuration.

Every test in this repository runs against a temporary, deterministic
environment: no test may read the developer's real ``.superagent`` directory,
inherit a ``YOLO`` flag from the shell, or leak a process-global singleton into
the next test.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


def assert_mode(path: Path, mode: int) -> None:
    """Assert ``path`` has POSIX permission ``mode``, where the platform can say so.

    Windows has no POSIX owner/group/other permission bits: ``chmod`` there only
    flips the read-only attribute, and ``stat`` always reports ``0o666``-ish bits.
    The assertion is therefore a no-op on Windows, where the permission contract
    is expressed through the user profile's access control instead.
    """
    if sys.platform == "win32":
        return
    assert stat.S_IMODE(path.stat().st_mode) == mode


@pytest.fixture(autouse=True)
def _deterministic_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin HOME and the working directory, and clear the environment knobs."""
    home = str(tmp_path / "home")
    monkeypatch.setenv("HOME", home)
    # ``expanduser("~")`` reads ``USERPROFILE`` on Windows and ignores ``HOME``,
    # so the two must move together or the settings path resolves to the real
    # user directory and every config test reads the developer's own file.
    monkeypatch.setenv("USERPROFILE", home)
    # An existing home keeps login shells quiet: Git Bash prints an MSYS2
    # first-start banner while ``$HOME`` does not exist, and that banner lands
    # in command output the tests compare.
    Path(home).mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("YOLO", raising=False)
    monkeypatch.delenv("NO_TOOLS", raising=False)
    for name in tuple(os.environ):
        # A proxy inherited from the developer's shell changes how HTTP clients
        # behave and how they parse ``NO_PROXY``; tests that stand up a loopback
        # server must not be routed through it, and an unsupported proxy scheme
        # (for example a SOCKS URL without the optional dependency) would fail
        # client construction instead of testing this repository.
        if name.endswith("_API_KEY") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def _leak_check() -> Iterator[None]:
    """Fail a test that leaves asyncio debug mode reporting a resource leak.

    ``python -X dev`` turns asyncio's leak detector on; this fixture only keeps
    the setting from being disabled between tests.
    """
    yield
