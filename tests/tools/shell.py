"""Shell facts the command-tool tests need on every platform.

The tools run commands through ``bash -lc``. On Windows that bash is Git Bash,
an MSYS2 build whose ``pwd`` prints ``/c/Users/...`` while the workspace API
speaks native ``C:\\Users\\...``; ``pwd -W`` asks for the native form. The
comparison below normalises separators and case so both forms name the same
directory without the tests hard-coding one shell's spelling.
"""

from __future__ import annotations

import os


def native_pwd_command() -> str:
    """The command that prints the shell's working directory in native form."""
    return "pwd -W" if os.name == "nt" else "pwd"


def reports_directory(reported: str, expected: str) -> bool:
    """Whether a shell's cwd report names ``expected``, in either separator style."""
    path = os.path.normpath(reported.strip().replace("/", os.sep))
    return os.path.normcase(path) == os.path.normcase(os.path.normpath(expected))
