"""The macOS strict sandbox, exercised through the real command tools.

Every test runs commands under ``sandbox-exec``, so the containment they prove
is the operating system's, not the tool layer's: writes outside the workspace,
reads of the home directory, and network connections are refused by Seatbelt
while the same commands succeed where the profile allows them.

``tests/conftest.py`` points ``HOME`` at a temporary directory, which the
sandbox protects like the account's real home; the tests plant their secrets
there instead of in the developer's home directory.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from super_agent.errors import Cancelled
from super_agent.runtime.protocol.run_context import RunContext, live_context
from super_agent.runtime.protocol.types import ToolCall
from super_agent.tools import Registry, default_sandbox_config, sandbox_darwin, sandboxed_registry
from super_agent.tools.commands import command_exit_error
from super_agent.tools.registry import registry_with_runner
from super_agent.tools.sandbox import SandboxConfig, command_runner, new_command_runner
from super_agent.tools.sandbox_darwin import seatbelt_profile, seatbelt_sandbox
from tests.tools.test_workspace import workspace_for

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt (sandbox-exec) exists only on macOS")

#: How long a test waits for the reaper to remove an ephemeral directory.
REAP_DEADLINE = 10.0


def _workspace(tmp_path: Path, name: str = "workspace") -> Path:
    workspace = tmp_path / name
    workspace.mkdir(parents=True)
    return Path(os.path.realpath(workspace))


def _registry(workspace: Path, config: SandboxConfig | None = None) -> Registry:
    """The production construction path, including the start-up probe."""
    if config is None:
        config = default_sandbox_config(str(workspace))
    return sandboxed_registry(config, workspace_for(workspace))


async def _run(
    registry: Registry,
    command: str,
    *,
    ctx: RunContext | None = None,
    timeout_seconds: int = 0,
    continue_on_error: bool = False,
) -> str:
    """Run ``command`` through the ``run_command`` tool."""
    payload: dict[str, object] = {"command": command, "continue_on_error": continue_on_error}
    if timeout_seconds:
        payload["timeout_seconds"] = timeout_seconds
    return await registry.run(ctx or live_context(), ToolCall(name="run_command", input=json.dumps(payload)))


async def _output(registry: Registry, command: str, *, timeout_seconds: int = 0) -> str:
    """The command's output, whatever its exit status."""
    return await _run(registry, command, timeout_seconds=timeout_seconds, continue_on_error=True)


def _scratch_of(home: str) -> Path:
    """The ephemeral directory a command reported through ``$HOME``."""
    scratch = Path(home).parent
    assert scratch.name.startswith("super-agent-sandbox-"), home
    assert str(scratch.parent) == os.path.realpath(tempfile.gettempdir())
    return scratch


async def _until_removed(path: Path) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + REAP_DEADLINE
    while path.exists():
        assert loop.time() < deadline, f"{path} was not removed"
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_strict_sandbox_writes_only_inside_the_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    registry = _registry(workspace)

    assert await _run(registry, "printf ready") == "ready"
    await _run(registry, "echo inside > inside.txt")
    assert (workspace / "inside.txt").read_text(encoding="utf-8") == "inside\n"

    # The blocked write is the sandbox's answer, so it surfaces as the command's
    # own non-zero exit, not as a failure to run it.
    with pytest.raises(command_exit_error):
        await _run(registry, f"echo planted > {outside / 'planted.txt'}")
    assert not (outside / "planted.txt").exists()

    home = Path(os.environ["HOME"])
    with pytest.raises(command_exit_error):
        await _run(registry, f"echo planted > {home / 'planted.txt'}")
    assert not (home / "planted.txt").exists()


@pytest.mark.asyncio
async def test_strict_sandbox_cannot_hard_link_an_outside_file_into_the_workspace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("original\n", encoding="utf-8")
    registry = _registry(workspace)

    # A hard link would make a workspace path an alias for the outside file.
    output = await _output(registry, f"ln {target} alias.txt; echo changed >> {target}")

    assert "Operation not permitted" in output
    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.asyncio
async def test_strict_sandbox_hides_the_home_directory(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    secret = Path(os.environ["HOME"]) / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    registry = _registry(workspace)

    read = await _output(registry, f"cat {secret}")
    # Imported here so that the module still loads on Windows, which has no pwd.
    import pwd

    account_home = pwd.getpwuid(os.getuid()).pw_dir
    listing = await _output(registry, f"ls {account_home}")

    assert "top secret" not in read
    assert "Operation not permitted" in read
    assert "Operation not permitted" in listing


@pytest.mark.asyncio
async def test_strict_sandbox_keeps_a_workspace_inside_home_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "account"
    monkeypatch.setenv("HOME", str(home))
    workspace = _workspace(home, "projects/app")
    (home / "secret.txt").write_text("top secret", encoding="utf-8")
    registry = _registry(workspace)

    output = await _output(
        registry,
        "pwd -P; echo kept > inside.txt && cat inside.txt; "
        "stat -f %N .. > /dev/null && echo parent-stat-ok; "
        "ls .. > /dev/null 2>&1 || echo parent-list-denied; "
        "cat ../../secret.txt",
    )

    lines = output.splitlines()
    assert lines[:4] == [str(workspace), "kept", "parent-stat-ok", "parent-list-denied"]
    assert "top secret" not in output
    assert "Operation not permitted" in output


@pytest.mark.asyncio
async def test_strict_sandbox_takes_paths_as_parameters_not_profile_text(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, 'ws "quoted" (paren) = eq; $x')
    registry = _registry(workspace)

    await _run(registry, "echo inside > inside.txt")
    output = await _output(registry, f"echo planted > {tmp_path / 'planted.txt'}")

    assert (workspace / "inside.txt").exists()
    assert "Operation not permitted" in output
    assert not (tmp_path / "planted.txt").exists()


@pytest.mark.asyncio
async def test_strict_sandbox_gives_each_command_an_ephemeral_home(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))
    command = 'printf "%s\\n" "$HOME" "$TMPDIR" "$XDG_CACHE_HOME"; touch "$HOME/h" "$TMPDIR/t" "$XDG_CACHE_HOME/c"'

    first = (await _run(registry, command)).splitlines()
    second = (await _run(registry, command)).splitlines()

    scratch = _scratch_of(first[0])
    assert first == [str(scratch / "home"), str(scratch / "tmp"), str(scratch / "cache")]
    assert _scratch_of(second[0]) != scratch
    await _until_removed(scratch)
    await _until_removed(_scratch_of(second[0]))


@pytest.mark.asyncio
async def test_strict_sandbox_removes_entries_the_command_locked(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))

    home = await _run(
        registry,
        'mkdir -p "$TMPDIR/sealed/inner" && touch "$TMPDIR/sealed/inner/f" "$HOME/frozen" && '
        'chmod 000 "$TMPDIR/sealed/inner" "$TMPDIR/sealed" && chflags uchg "$HOME/frozen" && printf %s "$HOME"',
    )

    await _until_removed(_scratch_of(home))


@pytest.mark.asyncio
async def test_strict_sandbox_removes_the_ephemeral_home_after_a_timeout(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))

    output = await _output(registry, 'echo "$HOME"; sleep 30', timeout_seconds=1)

    await _until_removed(_scratch_of(output.splitlines()[0]))


@pytest.mark.asyncio
async def test_strict_sandbox_removes_the_ephemeral_home_after_a_cancel(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    registry = _registry(workspace)
    ctx = RunContext()
    marker = workspace / "home.txt"

    call = asyncio.create_task(_run(registry, 'echo "$HOME" > home.txt; sleep 30', ctx=ctx))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + REAP_DEADLINE
    while not marker.exists() or not marker.read_text(encoding="utf-8").endswith("\n"):
        assert loop.time() < deadline, "the command never started"
        await asyncio.sleep(0.05)
    ctx.cancel()

    with pytest.raises(Cancelled):
        await call
    await _until_removed(_scratch_of(marker.read_text(encoding="utf-8").strip()))


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_network", [False, True])
async def test_strict_sandbox_follows_the_network_policy(tmp_path: Path, allow_network: bool) -> None:
    workspace = _workspace(tmp_path)
    config = default_sandbox_config(str(workspace))
    config.allow_network = allow_network
    registry = _registry(workspace, config)

    # Without a network namespace the host's loopback is the only one there is,
    # so it must be closed too when the network is denied.
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        output = await _output(registry, f"exec 3<>/dev/tcp/127.0.0.1/{port} && echo connected")

    if allow_network:
        assert "connected" in output
    else:
        assert "connected" not in output
        assert "Operation not permitted" in output


@pytest.mark.asyncio
async def test_strict_sandbox_keeps_local_sockets_inside_the_workspace(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))

    output = await _output(
        registry,
        "/usr/bin/nc -lU ipc.sock > got.txt & sleep 0.5; echo hello | /usr/bin/nc -U ipc.sock; wait; cat got.txt",
    )

    assert output.strip().endswith("hello")


@pytest.mark.asyncio
async def test_strict_sandbox_applies_the_limits_macos_can_honour(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = default_sandbox_config(str(workspace))
    config.cpu_seconds = 7
    config.max_open_files = 23
    config.max_processes = 17
    config.memory_bytes = 64 << 20
    registry = _registry(workspace, config)

    limits = await _run(registry, 'printf "%s %s %s %s" "$(ulimit -t)" "$(ulimit -Ht)" "$(ulimit -n)" "$(ulimit -Hn)"')
    untouched = await _run(registry, 'printf "%s %s" "$(ulimit -u)" "$(ulimit -v)"')

    assert limits == "7 7 23 23"
    # RLIMIT_NPROC counts the user's every process and RLIMIT_AS cannot be set,
    # so the sandbox leaves both alone rather than breaking every fork.
    processes, memory = untouched.split()
    assert processes != "17"
    assert memory == "unlimited"


@pytest.mark.asyncio
async def test_strict_sandbox_keeps_other_terminals_closed(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))
    controller, terminal = os.openpty()
    try:
        name = os.ttyname(terminal)
        foreign = await _output(registry, f"exec 3< {name} && echo opened; echo typed > {name}")
        # A pseudo-terminal opened inside the sandbox stays usable.
        own = await _output(registry, "/usr/bin/script -q /dev/null /bin/echo pty-ok < /dev/null")
    finally:
        os.close(terminal)
        os.close(controller)

    assert "opened" not in foreign
    assert foreign.count("Operation not permitted") == 2
    assert "pty-ok" in own


@pytest.mark.asyncio
async def test_strict_sandbox_cannot_signal_processes_outside_it(tmp_path: Path) -> None:
    registry = _registry(_workspace(tmp_path))

    output = await _output(registry, f"kill -0 {os.getpid()}")

    assert "Operation not permitted" in output


@pytest.mark.asyncio
async def test_bash_reports_a_blocked_write_as_a_result(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    registry = _registry(workspace)

    output = await registry.run(
        live_context(),
        ToolCall(name="bash", input=json.dumps({"command": f"touch {tmp_path / 'planted'}"})),
    )

    assert "Operation not permitted" in output
    assert "exit status 1" in output
    assert not (tmp_path / "planted").exists()


def test_strict_sandbox_refuses_to_start_without_sandbox_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_darwin, "SANDBOX_EXEC", str(tmp_path / "missing" / "sandbox-exec"))

    with pytest.raises(RuntimeError, match="requires sandbox-exec") as excinfo:
        _registry(_workspace(tmp_path))
    assert "sandbox.mode to off" in str(excinfo.value)


def test_strict_sandbox_refuses_to_start_when_the_profile_cannot_be_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox_darwin, "BASE_RULES", "(version 1)\n(not-a-rule)\n")

    with pytest.raises(RuntimeError, match="could not apply its Seatbelt profile") as excinfo:
        _registry(_workspace(tmp_path))
    assert "sandbox.mode to off" in str(excinfo.value)


def _contained_runner(workspace: Path) -> tuple[command_runner, seatbelt_sandbox]:
    context = workspace_for(workspace)
    runner = new_command_runner(default_sandbox_config(str(workspace)), context)
    assert isinstance(runner.sandbox, seatbelt_sandbox)
    return runner, runner.sandbox


@pytest.mark.asyncio
async def test_a_command_never_runs_when_its_profile_cannot_be_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    runner, _ = _contained_runner(workspace)
    registry = registry_with_runner(runner, workspace_for(workspace))
    monkeypatch.setattr(sandbox_darwin, "BASE_RULES", "(version 1)\n(not-a-rule)\n")

    output = await _output(registry, "touch ran.txt")

    assert "sandbox-exec:" in output
    assert "exit status" in output
    assert not (workspace / "ran.txt").exists()


@pytest.mark.asyncio
async def test_a_command_never_runs_when_sandbox_exec_disappears(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner, sandbox = _contained_runner(workspace)
    registry = registry_with_runner(runner, workspace_for(workspace))
    sandbox.sandbox_exec = str(tmp_path / "missing" / "sandbox-exec")

    output = await _output(registry, "touch ran.txt")

    assert "super-agent sandbox:" in output
    assert "exit status 125" in output
    assert not (workspace / "ran.txt").exists()


def test_a_downgrade_flag_does_not_disable_the_macos_sandbox(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    config = default_sandbox_config(str(workspace))
    config.downgraded = True

    runner = new_command_runner(config, workspace_for(workspace))

    assert isinstance(runner.sandbox, seatbelt_sandbox)


def test_profile_reads_every_path_from_a_parameter(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = str(home / "src" / "app")
    scratch_parent = str(tmp_path / "scratch")

    denied_profile, denied = seatbelt_profile(workspace, (str(home),), scratch_parent, False)
    allowed_profile, _ = seatbelt_profile(workspace, (str(home),), scratch_parent, True)

    assert str(tmp_path) not in denied_profile
    values = dict(pair.split("=", 1) for pair in denied[1::2])
    assert denied[0::2] == ["-D"] * len(values)
    assert values["WORKSPACE"] == workspace
    assert values["PROTECTED_0"] == str(home)
    # Only the directories between the protected home and the workspace expose
    # their metadata; the workspace itself is covered by the writable rule.
    assert sorted(value for key, value in values.items() if key.startswith("ANCESTOR_")) == [
        str(home),
        str(home / "src"),
    ]
    assert "(remote ip)" not in denied_profile
    assert "(remote ip)" in allowed_profile
