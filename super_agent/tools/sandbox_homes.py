"""The home directories a strict sandbox hides from commands.

Linux and macOS hide the same directories, each with its own mechanism (see
``docs/spec/tools.md``), so which directories count as home is decided here
once.
"""

from __future__ import annotations

import contextlib
import os


def protected_homes() -> tuple[str, ...]:
    """The user's home directories, resolved: ``HOME`` and the account's own.

    Both count, since settings and credentials follow ``HOME`` while the
    account's directory is where the user's keys live. A relative ``HOME`` names
    no directory, and the filesystem root is never protected, whatever ``HOME``
    says.
    """
    # Imported here so that the module, and the tests that import it, still
    # load on Windows, which has no ``pwd``.
    import pwd

    candidates = [os.path.expanduser("~")]
    # An account missing from the user database has no directory of its own.
    with contextlib.suppress(KeyError):
        candidates.append(pwd.getpwuid(os.getuid()).pw_dir)
    result: list[str] = []
    for candidate in candidates:
        if not os.path.isabs(candidate):
            continue
        resolved = os.path.realpath(candidate)
        if resolved != os.sep and resolved not in result:
            result.append(resolved)
    return tuple(result)
