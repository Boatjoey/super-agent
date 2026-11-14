"""The per-command launcher of the macOS strict sandbox.

``sandbox_darwin.py`` runs this file as a script, with ``python -I -S``, in front
of every sandboxed command. The launcher itself runs outside the sandbox: it
creates the command's ephemeral directory, arranges for its removal, applies the
resource limits, and then replaces itself with ``sandbox-exec``, which applies
the Seatbelt profile before the command starts. Every failure exits before that
``exec``, so the command never runs without ``sandbox-exec``.

Removing the directory cannot be left to a ``finally`` here: the command tools
end a timed-out or cancelled call by sending ``SIGKILL`` to the whole process
group, which no handler survives. A detached reaper in its own session, outside
that group, waits instead for end-of-file on a pipe whose write end the command
and its children inherit. End-of-file therefore arrives only after every process
that could still use the directory has exited, however it exited.

The file uses the standard library only and imports little, because it starts
before every command and ``-S`` leaves the project's dependencies off
``sys.path``.

Arguments: ``SCRATCH_PARENT CPU_SECONDS MAX_OPEN_FILES COUNT``, then ``COUNT``
words of the ``sandbox-exec`` command line (its path, profile, and ``-D``
parameters), then the command and its arguments.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import sys
import tempfile

#: The exit status of a launch that failed before the command could start.
LAUNCH_FAILURE = 125

#: The Seatbelt parameter naming the ephemeral directory. The profile in
#: ``sandbox_darwin.py`` reads it under the same name.
SCRATCH_PARAMETER = "SCRATCH"


def main(argv: list[str]) -> int:
    """Launch the command ``argv`` describes; return only when that fails."""
    try:
        scratch_parent = argv[0]
        cpu_seconds = int(argv[1])
        max_open_files = int(argv[2])
        count = int(argv[3])
    except (IndexError, ValueError) as error:
        return _fail(f"invalid launcher arguments: {error}")
    sandbox_exec = argv[4 : 4 + count]
    command = argv[4 + count :]
    if count < 1 or len(sandbox_exec) != count or not command:
        return _fail("invalid launcher arguments: missing the sandbox-exec command line or the command")
    try:
        scratch = tempfile.mkdtemp(prefix="super-agent-sandbox-", dir=scratch_parent)
    except OSError as error:
        return _fail(f"cannot create the ephemeral directory: {error}")
    try:
        read_end, write_end = os.pipe()
        _start_reaper(scratch, read_end, write_end)
        os.close(read_end)
        # The write end is what keeps the reaper waiting, so the command and
        # everything it starts must inherit it.
        os.set_inheritable(write_end, True)
        home = os.path.join(scratch, "home")
        temporary = os.path.join(scratch, "tmp")
        cache = os.path.join(scratch, "cache")
        for directory in (home, temporary, cache):
            os.mkdir(directory, 0o700)
        _apply_limits(cpu_seconds, max_open_files)
        environment = dict(os.environ)
        environment.update(HOME=home, TMPDIR=temporary, XDG_CACHE_HOME=cache)
        os.execve(
            sandbox_exec[0],
            [*sandbox_exec, "-D", f"{SCRATCH_PARAMETER}={scratch}", "--", *command],
            environment,
        )
    except (OSError, ValueError) as error:
        _remove(scratch)
        return _fail(str(error))
    return LAUNCH_FAILURE  # pragma: no cover - execve does not return


def _start_reaper(scratch: str, read_end: int, write_end: int) -> None:
    """Start the process that removes ``scratch`` once the pipe reaches EOF.

    The intermediate child starts a new session and exits right away, so the
    reaper belongs to neither the command's process group nor its process tree.
    """
    pid = os.fork()
    if pid == 0:
        status = 0
        try:
            os.setsid()
            if os.fork() == 0:
                try:
                    _reap(scratch, read_end, write_end)
                finally:
                    os._exit(0)
        except BaseException:
            status = 1
        os._exit(status)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise OSError("cannot start the reaper of the ephemeral directory")


def _reap(scratch: str, read_end: int, write_end: int) -> None:
    """Wait until no process holds the write end, then remove ``scratch``."""
    os.close(write_end)
    # The reaper must not hold the command's output pipe open, or the caller
    # would keep reading until the reaper exits.
    devnull = os.open(os.devnull, os.O_RDWR)
    for descriptor in (0, 1, 2):
        if descriptor != read_end:
            os.dup2(devnull, descriptor)
    if devnull > 2:
        os.close(devnull)
    while os.read(read_end, 4096):
        pass
    _remove(scratch)


def _apply_limits(cpu_seconds: int, max_open_files: int) -> None:
    """Bound CPU time and open files, the limits macOS can apply to one command.

    Each limit is set as both the soft and the hard limit, so the command cannot
    raise it, unless a lower hard limit is already in force.
    """
    # Imported here so that ``sandbox_darwin.py`` can import this module's
    # constants on Windows, which has no ``resource``.
    import resource

    for which, value in ((resource.RLIMIT_CPU, cpu_seconds), (resource.RLIMIT_NOFILE, max_open_files)):
        _, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(which, (value, value))


def _remove(path: str) -> None:
    """Delete ``path``, including entries the command made read-only or immutable."""
    _unlock(path)
    for root, directories, files in os.walk(path):
        for name in (*directories, *files):
            _unlock(os.path.join(root, name))
    shutil.rmtree(path, ignore_errors=True)


def _unlock(path: str) -> None:
    """Clear file flags and make a directory searchable, never following links."""
    if sys.platform == "darwin":
        with contextlib.suppress(OSError):
            os.chflags(path, 0, follow_symlinks=False)
    with contextlib.suppress(OSError):
        if stat.S_ISDIR(os.lstat(path).st_mode):
            os.chmod(path, stat.S_IRWXU)


def _fail(message: str) -> int:
    """Report a launch failure; the command did not run."""
    sys.stderr.write(f"super-agent sandbox: {message}\n")
    return LAUNCH_FAILURE


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
