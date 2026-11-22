"""Strict command isolation with bubblewrap and prlimit.

The argument list is fixed: the host root is mounted read-only, the user's home
directories are covered by empty tmpfs mounts, the workspace is the only
writable host bind, temporary directories are ephemeral, networking follows the
configured policy, and ``prlimit`` bounds CPU time, address space, process
count, and open files.

bubblewrap applies its mount arguments in order, each on top of what the earlier
ones mounted, while a bind always takes its source from the host. Each home
tmpfs therefore comes after the root, which it covers, and before the workspace
bind, so that a workspace inside a home is mounted over the tmpfs rather than
hidden by it. The homes also come before ``/tmp`` and ``/var/tmp``: a home below
either is covered once more instead of leaving an empty mount point behind.

The type import is guarded because ``sandbox.py`` selects this module at import
time, so importing it back at runtime would be circular.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from collections.abc import Sequence
from typing import TYPE_CHECKING

from super_agent.tools.sandbox_homes import protected_homes

if TYPE_CHECKING:
    from super_agent.tools.sandbox import SandboxConfig


@dataclasses.dataclass(slots=True)
class BubblewrapSandbox:
    """Wraps a command in ``bwrap`` and then ``prlimit``."""

    bwrap: str
    prlimit: str
    config: SandboxConfig
    #: Resolved home directories whose contents commands may not read.
    protected: tuple[str, ...]

    def wrap(self, workspace_root: str, cwd: str, name: str, args: list[str]) -> tuple[str, list[str], str]:
        """Return the ``bwrap`` command line that contains ``name``."""
        if workspace_root == "":
            raise RuntimeError("sandbox workspace is not configured")
        workspace_root = os.path.realpath(workspace_root, strict=True)
        if cwd == "":
            cwd = workspace_root
        abs_cwd = os.path.realpath(os.path.abspath(cwd), strict=True)
        relative = os.path.relpath(abs_cwd, workspace_root)
        if relative == ".." or relative.startswith(".." + os.sep):
            raise RuntimeError("sandbox cwd is outside workspace")

        sandbox_args = [
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind",
            "/",
            "/",
            *_home_mounts(self.protected, workspace_root),
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/var/tmp",
            "--bind",
            workspace_root,
            workspace_root,
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--dir",
            "/tmp/super-agent-home",
            "--dir",
            "/tmp/super-agent-cache",
            "--setenv",
            "HOME",
            "/tmp/super-agent-home",
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "XDG_CACHE_HOME",
            "/tmp/super-agent-cache",
            "--chdir",
            abs_cwd,
        ]
        if self.config.allow_network:
            sandbox_args.append("--share-net")
        sandbox_args.extend(
            [
                "--",
                self.prlimit,
                "--cpu=" + str(self.config.cpu_seconds),
                "--as=" + str(self.config.memory_bytes),
                "--nproc=" + str(self.config.max_processes),
                "--nofile=" + str(self.config.max_open_files),
                "--",
                name,
                *args,
            ]
        )
        return self.bwrap, sandbox_args, workspace_root


def _home_mounts(protected: Sequence[str], workspace_root: str) -> list[str]:
    """The ``--tmpfs`` arguments that cover each protected home.

    A home the workspace equals or contains belongs to the workspace and is left
    to its bind. A home inside another protected home is covered along with it.
    A home that does not exist has nothing to hide, and bubblewrap could not
    create its mount point in the read-only root.
    """
    homes = list(dict.fromkeys(protected))
    arguments: list[str] = []
    for home in homes:
        if _within(home, workspace_root):
            continue
        if any(other != home and _within(home, other) for other in homes):
            continue
        if os.path.isdir(home):
            arguments.extend(["--tmpfs", home])
    return arguments


def _within(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or lies below it."""
    relative = os.path.relpath(path, root)
    return relative != ".." and not relative.startswith(".." + os.sep)


def new_platform_sandbox(config: SandboxConfig) -> BubblewrapSandbox:
    """Build the bubblewrap sandbox, or refuse when its tools are missing."""
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise RuntimeError(
            "strict sandbox requires bubblewrap: bwrap not found in PATH "
            "(install the bubblewrap package, or set sandbox.mode to off)"
        )
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        raise RuntimeError(
            "strict sandbox requires prlimit: prlimit not found in PATH "
            "(install util-linux, or set sandbox.mode to off)"
        )
    return BubblewrapSandbox(bwrap=bwrap, prlimit=prlimit, config=config, protected=protected_homes())
