"""Strict command isolation on macOS with Seatbelt (``sandbox-exec``).

Every command runs under a deny-by-default Seatbelt profile: the host filesystem
is readable but not writable, the user's home directory is not readable, the
workspace and a per-command ephemeral directory are the only writable places,
the network follows the configured policy, and CPU time and open files are
bounded. ``sandbox_darwin_launcher.py`` creates and removes the ephemeral
directory and applies the limits; this module builds the profile and the command
line, and refuses to construct a sandbox that ``sandbox-exec`` cannot apply.

Paths never enter the profile text. They are passed with ``-D NAME=value`` and
read with ``(param "NAME")``, so a quote or parenthesis in a path cannot change
the policy. Seatbelt matches resolved paths, which is why every path is resolved
first: ``/tmp`` is ``/private/tmp`` and ``/var`` is ``/private/var``.

For rules on the same operation, Seatbelt applies the one written last; that is
what lets the workspace be allowed again after the home directory is denied. A
later rule on a wildcard operation (``file-read*``) does not override an earlier
rule on a specific operation (``file-read-data``), so every overriding rule
below names the same operations as the rule it overrides.

The limits macOS cannot bound for one command are left alone rather than
approximated: ``RLIMIT_AS`` cannot be set at all, and ``RLIMIT_NPROC`` counts
every process the user runs, so ``memory_bytes`` and ``max_processes`` do not
apply here.

The type import is guarded because ``sandbox.py`` selects this module at import
time, so importing it back at runtime would be circular.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Final

from super_agent.tools.env import child_env
from super_agent.tools.sandbox_darwin_launcher import SCRATCH_PARAMETER
from super_agent.tools.sandbox_homes import protected_homes

if TYPE_CHECKING:
    from super_agent.tools.sandbox import SandboxConfig

#: Seatbelt's front end. It ships with macOS, so it is never looked up in PATH,
#: where a directory the agent can write could shadow it.
SANDBOX_EXEC: Final[str] = "/usr/bin/sandbox-exec"

#: The script that runs in front of every sandboxed command.
LAUNCHER: Final[str] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_darwin_launcher.py")

#: How long constructing the sandbox waits for its trial command.
PROBE_TIMEOUT: Final[float] = 30.0

#: The rules every command runs under, before the per-command paths.
BASE_RULES: Final[str] = r"""(version 1)
(deny default)

; Programs may run and fork, but may signal and inspect only processes in this
; sandbox: not the agent, and not the user's other processes.
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))

; System information and the services ordinary tools look up: user and group
; records, logging, notifications, preferences (served only within what the
; file rules allow), and the per-user directory lookup.
(allow sysctl-read)
(allow ipc-posix-sem)
(allow ipc-posix-shm-read*
  (ipc-posix-name "apple.shm.notification_center")
  (ipc-posix-name-prefix "apple.cfprefs."))
(allow mach-lookup
  (global-name "com.apple.bsd.dirhelper")
  (global-name "com.apple.cfprefsd.agent")
  (global-name "com.apple.cfprefsd.daemon")
  (global-name "com.apple.logd")
  (global-name "com.apple.system.logger")
  (global-name "com.apple.system.notification_center")
  (global-name "com.apple.system.opendirectoryd.libinfo")
  (global-name "com.apple.system.opendirectoryd.membership"))
(allow network-outbound (literal "/private/var/run/syslog"))

; The host filesystem is readable. Other sessions' terminals are not, since
; reading one steals its keystrokes; pseudo-terminals opened in this sandbox
; carry an extension that keeps them usable.
(allow file-read* file-test-existence)
(deny file-read-data
  (regex #"^/dev/ttys[0-9]+$")
  (regex #"^/dev/(tty|pty)[p-w][0-9a-f]$"))
(allow pseudo-tty)
(allow file-read* file-write* file-ioctl
  (literal "/dev/ptmx")
  (literal "/dev/tty"))
(allow file-read-data file-write-data file-ioctl
  (require-all
    (regex #"^/dev/ttys[0-9]+$")
    (extension "com.apple.sandbox.pty")))
(allow file-write-data
  (literal "/dev/null")
  (literal "/dev/zero"))
(allow file-read* file-write-data file-ioctl (literal "/dev/dtracehelper"))
(allow file-read* file-write*
  (literal "/dev/stdin")
  (literal "/dev/stdout")
  (literal "/dev/stderr")
  (subpath "/dev/fd"))
"""

#: Read and write access to the workspace and the ephemeral directory. It comes
#: after the home-directory denial so that a workspace inside home stays usable.
WRITABLE_RULES: Final[str] = rf"""(allow file-read* file-write* file-test-existence file-link
  (subpath (param "WORKSPACE"))
  (subpath (param "{SCRATCH_PARAMETER}")))
(allow network-bind
  (local unix-socket (subpath (param "WORKSPACE")))
  (local unix-socket (subpath (param "{SCRATCH_PARAMETER}"))))
(allow network-outbound
  (remote unix-socket (subpath (param "WORKSPACE")))
  (remote unix-socket (subpath (param "{SCRATCH_PARAMETER}"))))
"""

#: IP networking, name resolution, and certificate trust, for ``allow_network``.
#: Local sockets elsewhere, such as an SSH agent or a container daemon, stay
#: closed even then.
NETWORK_RULES: Final[str] = r"""(allow network-outbound (remote ip))
(allow network-inbound (local ip))
(allow network-bind (local ip))
(allow system-socket)
(allow network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))
(allow mach-lookup
  (global-name "com.apple.SystemConfiguration.DNSConfiguration")
  (global-name "com.apple.SystemConfiguration.configd")
  (global-name "com.apple.dnssd.service")
  (global-name "com.apple.networkd")
  (global-name "com.apple.nehelper")
  (global-name "com.apple.ocspd")
  (global-name "com.apple.trustd")
  (global-name "com.apple.trustd.agent"))
"""


@dataclasses.dataclass(slots=True)
class SeatbeltSandbox:
    """Runs a command through the launcher and ``sandbox-exec``."""

    sandbox_exec: str
    #: The interpreter that runs the launcher, outside the sandbox.
    python: str
    launcher: str
    config: SandboxConfig
    #: Resolved directories whose contents commands may not read.
    protected: tuple[str, ...]
    #: The resolved directory that holds each command's ephemeral directory.
    scratch_parent: str

    def wrap(self, workspace_root: str, cwd: str, name: str, args: list[str]) -> tuple[str, list[str], str]:
        """Return the launcher command line that contains ``name``."""
        if workspace_root == "":
            raise RuntimeError("sandbox workspace is not configured")
        workspace_root = os.path.realpath(workspace_root, strict=True)
        if cwd == "":
            cwd = workspace_root
        abs_cwd = os.path.realpath(os.path.abspath(cwd), strict=True)
        relative = os.path.relpath(abs_cwd, workspace_root)
        if relative == ".." or relative.startswith(".." + os.sep):
            raise RuntimeError("sandbox cwd is outside workspace")

        profile, parameters = seatbelt_profile(
            workspace_root, self.protected, self.scratch_parent, self.config.allow_network
        )
        sandbox_exec = [self.sandbox_exec, "-p", profile, *parameters]
        launcher_args = [
            "-I",
            "-S",
            self.launcher,
            self.scratch_parent,
            str(self.config.cpu_seconds),
            str(self.config.max_open_files),
            str(len(sandbox_exec)),
            *sandbox_exec,
            name,
            *args,
        ]
        return self.python, launcher_args, abs_cwd

    def probe(self, workspace_root: str) -> None:
        """Run a trial command, refusing a sandbox ``sandbox-exec`` cannot apply."""
        executable, args, cwd = self.wrap(workspace_root, "", "/usr/bin/true", [])
        try:
            completed = subprocess.run(
                [executable, *args],
                cwd=cwd,
                env=child_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                f"strict sandbox could not run sandbox-exec: {error} (set sandbox.mode to off to run commands unsandboxed)"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip() or f"exit status {completed.returncode}"
            raise RuntimeError(
                f"strict sandbox could not apply its Seatbelt profile: {detail} "
                "(set sandbox.mode to off to run commands unsandboxed)"
            )


def seatbelt_profile(
    workspace_root: str, protected: Sequence[str], scratch_parent: str, allow_network: bool
) -> tuple[str, list[str]]:
    """The profile for one command and its ``-D`` parameters.

    The launcher adds the ephemeral directory's parameter itself, because it
    creates that directory. Parameter names are generated here; parameter values
    are the only place a path appears.
    """
    values: list[tuple[str, str]] = [("WORKSPACE", workspace_root)]
    sections = [BASE_RULES]
    if protected:
        names = [f"PROTECTED_{index}" for index in range(len(protected))]
        values.extend(zip(names, protected, strict=True))
        sections.append(_rule("deny", "file-read* file-test-existence", "subpath", names))
        # A workspace or ephemeral directory inside a protected one must stay
        # reachable: the directories above it expose their metadata, not their
        # listings. The ephemeral directory sits inside ``scratch_parent``.
        above = [*_ancestors(workspace_root), scratch_parent, *_ancestors(scratch_parent)]
        ancestors = [path for path in dict.fromkeys(above) if any(_within(path, root) for root in protected)]
        if ancestors:
            names = [f"ANCESTOR_{index}" for index in range(len(ancestors))]
            values.extend(zip(names, ancestors, strict=True))
            sections.append(_rule("allow", "file-read-metadata file-test-existence", "literal", names))
    sections.append(WRITABLE_RULES)
    if allow_network:
        sections.append(NETWORK_RULES)
    parameters: list[str] = []
    for name, value in values:
        parameters.extend(["-D", f"{name}={value}"])
    return "\n".join(sections), parameters


def _rule(action: str, operations: str, filter_name: str, parameter_names: Iterable[str]) -> str:
    filters = "\n".join(f'  ({filter_name} (param "{name}"))' for name in parameter_names)
    return f"({action} {operations}\n{filters})\n"


def _ancestors(path: str) -> list[str]:
    """Every directory above ``path``, nearest first, up to the root."""
    result: list[str] = []
    parent = os.path.dirname(path)
    while parent not in result:
        result.append(parent)
        parent = os.path.dirname(parent)
    return result


def _within(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or lies below it."""
    relative = os.path.relpath(path, root)
    return relative != ".." and not relative.startswith(".." + os.sep)


def new_platform_sandbox(config: SandboxConfig) -> SeatbeltSandbox:
    """Build the Seatbelt sandbox, or refuse when it cannot contain commands."""
    if not os.access(SANDBOX_EXEC, os.X_OK):
        raise RuntimeError(
            f"strict sandbox requires sandbox-exec: {SANDBOX_EXEC} not found "
            "(it ships with macOS; or set sandbox.mode to off)"
        )
    if not sys.executable or not os.path.isfile(LAUNCHER):
        raise RuntimeError("strict sandbox cannot locate its launcher (set sandbox.mode to off)")
    sandbox = SeatbeltSandbox(
        sandbox_exec=SANDBOX_EXEC,
        python=sys.executable,
        launcher=LAUNCHER,
        config=config,
        protected=protected_homes(),
        scratch_parent=os.path.realpath(tempfile.gettempdir()),
    )
    sandbox.probe(config.workspace)
    return sandbox
