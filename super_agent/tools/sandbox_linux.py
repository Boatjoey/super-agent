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

Constructing the sandbox runs a trial command through that same argument list,
so a system on which bubblewrap cannot build its namespaces refuses at startup,
naming the cause and the remedies, instead of failing every command. The common
cause is Ubuntu's AppArmor restriction of unprivileged user namespaces: bwrap
may create the user namespace but holds no capabilities inside it, so it cannot
configure loopback in its network namespace. The trial never retries with
weaker isolation.

The type import is guarded because ``sandbox.py`` selects this module at import
time, so importing it back at runtime would be circular.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from super_agent.tools.env import child_env
from super_agent.tools.sandbox_homes import protected_homes

if TYPE_CHECKING:
    from super_agent.tools.sandbox import SandboxConfig

#: How long constructing the sandbox waits for its trial command.
PROBE_TIMEOUT: Final[float] = 30.0

#: Ubuntu's switch for AppArmor's restriction of unprivileged user namespaces.
APPARMOR_USERNS_SYSCTL: Final[str] = "kernel.apparmor_restrict_unprivileged_userns"

#: Where that switch is read. Any user may read it; kernels without the
#: restriction do not have it.
APPARMOR_USERNS_SYSCTL_PATH: Final[str] = "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"

#: The bwrap that Ubuntu's ``bwrap-userns-restrict`` AppArmor profile attaches to.
UBUNTU_BWRAP: Final[str] = "/usr/bin/bwrap"


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

    def probe(self, workspace_root: str) -> None:
        """Run ``true`` through the real command line, refusing a sandbox bwrap cannot start."""
        executable, args, cwd = self.wrap(workspace_root, "", "true", [])
        try:
            completed = subprocess.run(
                [executable, *args],
                cwd=cwd,
                env=child_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=PROBE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                f"strict sandbox could not run bwrap: {error} (set sandbox.mode to off to run commands unsandboxed)"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip() or f"exit status {completed.returncode}"
            raise RuntimeError(_trial_refusal(self.bwrap, detail))


def _trial_refusal(bwrap: str, detail: str) -> str:
    """The startup refusal for a trial command that bubblewrap could not run.

    The AppArmor profile must name the executable's resolved path, which is the
    path AppArmor attaches profiles to.
    """
    target = os.path.realpath(bwrap)
    if not _apparmor_restricts_userns():
        remedy = (
            f"bubblewrap needs unprivileged user namespaces: if this system restricts them, allow them for {target}, "
            "or set sandbox.mode to off, which runs commands without isolation."
        )
        return f"strict sandbox could not start bubblewrap: {detail}\n{remedy}"
    profile = f"load an AppArmor profile that grants userns to {target}"
    if target == UBUNTU_BWRAP:
        profile += (
            ", such as bwrap-userns-restrict from Ubuntu's apparmor-profiles package"
            " (copy it from /usr/share/apparmor/extra-profiles to /etc/apparmor.d, then apparmor_parser -r it)"
        )
    lines = [
        f"strict sandbox could not start bubblewrap: {detail}",
        f"This system restricts unprivileged user namespaces with AppArmor ({APPARMOR_USERNS_SYSCTL} = 1), "
        "which is the likely cause. Fix it with one of:",
        f"  - {profile}",
        f"  - run `sudo sysctl -w {APPARMOR_USERNS_SYSCTL}=0`, which lifts the restriction for every program "
        "on the system, so it no longer mitigates kernel exploits that abuse user namespaces",
        "  - set sandbox.mode to off, which runs commands without isolation",
    ]
    return "\n".join(lines)


def _apparmor_restricts_userns() -> bool:
    """Whether AppArmor restricts unprivileged user namespaces on this kernel."""
    try:
        with open(APPARMOR_USERNS_SYSCTL_PATH, encoding="ascii") as switch:
            return switch.read().strip() == "1"
    except (OSError, ValueError):
        return False


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
    """Build the bubblewrap sandbox, or refuse when its tools are missing or it cannot contain commands."""
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
    sandbox = BubblewrapSandbox(bwrap=bwrap, prlimit=prlimit, config=config, protected=protected_homes())
    sandbox.probe(config.workspace)
    return sandbox
