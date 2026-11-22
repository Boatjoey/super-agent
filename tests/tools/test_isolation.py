"""Containment and resource bounds.

The symlink tests prove the workspace check resolves before it trusts, the
output tests prove a model-supplied limit cannot buffer an arbitrary amount of
memory, the environment tests prove credentials do not reach a child, and the
process-tree test proves a background job dies with the call that started it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final, NoReturn

import pytest

from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ToolCall
from super_agent.tools import default_registry, default_sandbox_config, sandboxed_registry
from super_agent.tools.commands import CommandExitError, max_output_bytes
from super_agent.tools.sandbox_homes import protected_homes
from super_agent.tools.sandbox_linux import BubblewrapSandbox, new_platform_sandbox
from tests.helpers import spawn_tree
from tests.tools.test_workspace import workspace_for

REPO_ROOT = Path(__file__).resolve().parents[2]
TRUNCATION_MARKER = "\n... truncated"


@pytest.mark.asyncio
async def test_read_file_rejects_a_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    try:
        os.symlink(outside, worktree / "link")
    except OSError:
        pytest.skip("symlinks unavailable")
    registry = default_registry(workspace_for(worktree))

    # A lexical containment check accepts "link/secret.txt" because the
    # relative path contains no "..". Resolving the symlink first rejects it.
    with pytest.raises(RuntimeError, match="outside readable workspace roots"):
        await registry.run(live_context(), ToolCall(name="read_file", input='{"path":"link/secret.txt"}'))


@pytest.mark.asyncio
async def test_write_file_rejects_a_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    try:
        os.symlink(outside, worktree / "link")
    except OSError:
        pytest.skip("symlinks unavailable")
    registry = default_registry(workspace_for(worktree))

    with pytest.raises(RuntimeError, match="outside writable workspace roots"):
        await registry.run(
            live_context(),
            ToolCall(name="write_file", input='{"path":"link/planted.txt","content":"owned"}'),
        )
    assert not (outside / "planted.txt").exists()


@pytest.mark.asyncio
async def test_run_command_caps_the_requested_output_limit(tmp_path: Path) -> None:
    registry = default_registry(workspace_for(tmp_path))
    # The model asks for a 100 MB limit. Without a ceiling the command's entire
    # output is buffered in memory.
    payload = {
        "command": "head -c 400000 /dev/zero | tr '\\0' 'a'",
        "max_output_bytes": 100_000_000,
    }

    got = await registry.run(live_context(), ToolCall(name="run_command", input=json.dumps(payload)))

    assert len(got) <= max_output_bytes + len(TRUNCATION_MARKER)
    assert "truncated" in got


@pytest.mark.asyncio
async def test_bash_truncates_output(tmp_path: Path) -> None:
    registry = default_registry(workspace_for(tmp_path))
    payload = {"command": "head -c 400000 /dev/zero | tr '\\0' 'a'"}

    got = await registry.run(live_context(), ToolCall(name="bash", input=json.dumps(payload)))

    assert len(got) <= max_output_bytes + len(TRUNCATION_MARKER)


@pytest.mark.asyncio
async def test_run_command_hides_the_credential_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_AGENT_TEST_API_KEY", "sk-secret-value")
    registry = default_registry(workspace_for(tmp_path))

    got = await registry.run(
        live_context(),
        ToolCall(name="run_command", input='{"command":"printenv SUPER_AGENT_TEST_API_KEY || echo absent"}'),
    )

    assert "sk-secret-value" not in got
    assert "absent" in got


@pytest.mark.asyncio
async def test_run_command_keeps_the_ordinary_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPER_AGENT_TEST_PLAIN", "visible")
    registry = default_registry(workspace_for(tmp_path))

    # Scrubbing must not be so aggressive that ordinary variables disappear.
    got = await registry.run(
        live_context(),
        ToolCall(name="run_command", input='{"command":"printenv SUPER_AGENT_TEST_PLAIN"}'),
    )

    assert "visible" in got


def _spawn_tree_command(marker: Path) -> str:
    return " ".join(
        [
            f"PYTHONPATH={shlex.quote(str(REPO_ROOT))}",
            shlex.quote(sys.executable),
            "-m",
            "tests.helpers.spawn_tree",
            shlex.quote(str(marker)),
        ]
    )


@pytest.mark.asyncio
async def test_run_command_starts_the_helper_grandchild(tmp_path: Path) -> None:
    """The process-tree test is only meaningful if the grandchild really runs."""
    registry = default_registry(workspace_for(tmp_path))
    payload = {
        "command": _spawn_tree_command(tmp_path / "probe"),
        "timeout_seconds": 1,
        # The output is what proves the tree started, so the timeout is not
        # raised here.
        "continue_on_error": True,
    }

    output = await registry.run(live_context(), ToolCall(name="run_command", input=json.dumps(payload)))

    assert spawn_tree.READY_MARKER in output


@pytest.mark.asyncio
async def test_run_command_timeout_kills_the_process_tree(tmp_path: Path) -> None:
    registry = default_registry(workspace_for(tmp_path))
    marker = tmp_path / "survivor"

    # The backgrounded grandchild outlives the direct child. Killing only the
    # direct child would orphan it, and it would create the marker afterwards.
    with pytest.raises(TimeoutError):
        await registry.run(
            live_context(),
            ToolCall(
                name="run_command",
                input=json.dumps({"command": _spawn_tree_command(marker), "timeout_seconds": 1}),
            ),
        )

    await asyncio.sleep(4)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform in ("linux", "darwin"), reason="Linux and macOS have a real strict sandbox")
def test_strict_sandbox_fails_closed_on_unsupported_platforms(tmp_path: Path) -> None:
    """Strict is the default, so an unsupported platform must refuse outright."""
    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "strict sandbox is currently supported only on Linux and macOS; set sandbox.mode to off explicitly"
        ),
    ):
        sandboxed_registry(default_sandbox_config(str(tmp_path)), workspace_for(tmp_path))


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
@pytest.mark.asyncio
async def test_strict_sandbox_requires_bubblewrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    with pytest.raises(RuntimeError, match="requires bubblewrap") as excinfo:
        sandboxed_registry(default_sandbox_config(str(tmp_path)), workspace_for(tmp_path))
    assert "sandbox.mode to off" in str(excinfo.value)


#: Set to ``1`` where the strict sandbox must be able to run, as CI does after
#: lifting the runner's restriction on unprivileged user namespaces. A strict
#: sandbox test the environment cannot run then fails instead of skipping, so
#: these tests cannot quietly stop running.
REQUIRE_SANDBOX_ENV: Final[str] = "SUPER_AGENT_TEST_REQUIRE_SANDBOX"


def _skip_or_fail(reason: str) -> NoReturn:
    """Skip a strict sandbox test this environment cannot run, or fail where it must."""
    if os.environ.get(REQUIRE_SANDBOX_ENV) == "1":
        pytest.fail(f"{reason} ({REQUIRE_SANDBOX_ENV}=1 requires the strict sandbox tests to run)")
    pytest.skip(reason)


def _namespace_refusal() -> str:
    """Why this kernel cannot start bubblewrap, or an empty string when it can.

    A kernel or security policy may forbid unprivileged user namespaces; Ubuntu
    24.04's AppArmor restriction, for one, stops bwrap from configuring loopback
    in its network namespace. That is an environment limit, not a sandbox
    regression: probe the capability directly and let the integration tests
    skip, unless ``REQUIRE_SANDBOX_ENV`` says this environment must allow it. A
    missing binary stays a failure, because it is a declared dependency.
    """
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return ""
    try:
        probe = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--unshare-all", "--", "true"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return str(err)
    if probe.returncode == 0:
        return ""
    return (probe.stderr or probe.stdout).strip() or f"bwrap exited {probe.returncode}"


def _require_namespaces() -> None:
    """Skip, or fail, when this kernel cannot start bubblewrap."""
    refusal = _namespace_refusal()
    if refusal:
        _skip_or_fail(f"kernel namespaces unavailable: {refusal}")


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
@pytest.mark.asyncio
async def test_strict_sandbox_restricts_filesystem_network_and_resources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    config = default_sandbox_config(str(workspace))
    config.cpu_seconds = 7
    config.memory_bytes = 64 << 20
    config.max_processes = 17
    config.max_open_files = 23
    # Missing bubblewrap/prlimit is a declared dependency, not a reason to skip:
    # verify.sh fails on it before the tests run, and a bare pytest run should
    # surface it too.
    registry = sandboxed_registry(config, workspace_for(workspace))
    _require_namespaces()

    probe = await registry.run(live_context(), ToolCall(name="run_command", input='{"command":"printf ready"}'))
    assert probe == "ready"

    inside = workspace / "inside"
    command = f"touch {inside}; touch {outside / 'planted'}"
    # The blocked write is what the sandbox is being asked to produce, so the
    # type is the tool's own: a non-zero exit is a result the model reads, not
    # the ``RuntimeError`` that means the sandbox itself could not run.
    with pytest.raises(CommandExitError):
        await registry.run(
            live_context(),
            ToolCall(name="run_command", input=json.dumps({"command": command})),
        )
    assert inside.exists()
    assert not (outside / "planted").exists()

    isolated = await registry.run(
        live_context(),
        ToolCall(
            name="run_command",
            input=json.dumps({"command": "awk 'NR > 1 { exit 1 }' /proc/net/route && printf isolated"}),
        ),
    )
    assert "isolated" in isolated

    limits_command = 'printf \'%s %s %s\' "$(ulimit -v)" "$(ulimit -u)" "$(ulimit -n)"'
    limits = await registry.run(
        live_context(),
        ToolCall(name="run_command", input=json.dumps({"command": limits_command})),
    )
    assert limits == "65536 17 23"


#: What the home-directory test plants in the account's real home.
SECRET_TEXT: Final[str] = "top secret"


def _account_home() -> str:
    """The account's real home directory, resolved, where a test may plant files.

    ``tests/conftest.py`` points ``HOME`` at a temporary directory, so the real
    home comes from the user database.
    """
    # Imported here so that the module still loads on Windows, which has no pwd.
    import pwd

    try:
        home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        _skip_or_fail("this account has no entry in the user database")
    if home == os.sep or not os.path.isdir(home) or not os.access(home, os.W_OK):
        _skip_or_fail(f"the account's home directory {home} cannot hold test files")
    return home


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
@pytest.mark.asyncio
async def test_strict_sandbox_hides_the_real_home_and_keeps_a_workspace_inside_it() -> None:
    _require_namespaces()
    home = _account_home()
    # Everything this test creates in the real home carries one fresh name and
    # is removed afterwards.
    root = Path(tempfile.mkdtemp(prefix=".super-agent-sandbox-test-", dir=home))
    secret = root.with_name(root.name + ".secret")
    planted = root.with_name(root.name + ".planted")
    try:
        secret.write_text(SECRET_TEXT, encoding="utf-8")
        workspace = root / "projects" / "app"
        workspace.mkdir(parents=True)
        (workspace / "input.txt").write_text("from host\n", encoding="utf-8")
        registry = sandboxed_registry(default_sandbox_config(str(workspace)), workspace_for(workspace))
        command = "; ".join(
            [
                "pwd -P",
                "cat input.txt",
                "echo from sandbox > output.txt",
                f"ls -A {shlex.quote(home)}",
                f"test -e {shlex.quote(str(secret))} || echo secret-missing",
                f"echo planted > {shlex.quote(str(planted))} && echo planted",
                f"cat {shlex.quote(str(secret))}",
            ]
        )

        output = await registry.run(
            live_context(),
            ToolCall(name="run_command", input=json.dumps({"command": command, "continue_on_error": True})),
        )

        # The workspace is bound over the empty tmpfs that covers the home, so
        # the only entry left in the home is the directory leading to it.
        assert output.splitlines()[:5] == [str(workspace), "from host", root.name, "secret-missing", "planted"]
        assert SECRET_TEXT not in output
        assert (workspace / "output.txt").read_text(encoding="utf-8") == "from sandbox\n"
        # The write outside the workspace landed in the tmpfs and went with it.
        assert not planted.exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        secret.unlink(missing_ok=True)
        planted.unlink(missing_ok=True)


def _sandbox(tmp_path: Path, *, allow_network: bool = False, protected: tuple[str, ...] = ()) -> BubblewrapSandbox:
    config = default_sandbox_config(str(tmp_path))
    config.allow_network = allow_network
    return BubblewrapSandbox(bwrap="/usr/bin/bwrap", prlimit="/usr/bin/prlimit", config=config, protected=protected)


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_defaults_an_empty_cwd_to_the_workspace(tmp_path: Path) -> None:
    workspace = os.path.realpath(tmp_path)

    _, args, cwd = _sandbox(tmp_path).wrap(str(tmp_path), "", "true", [])

    assert cwd == workspace
    assert args[args.index("--chdir") + 1] == workspace


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_refuses_a_cwd_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(RuntimeError, match="outside workspace"):
        _sandbox(workspace).wrap(str(workspace), str(outside), "true", [])


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_refuses_a_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="workspace is not configured"):
        _sandbox(tmp_path).wrap("", str(tmp_path), "true", [])


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_shares_the_network_only_when_allowed(tmp_path: Path) -> None:
    _, denied, _ = _sandbox(tmp_path).wrap(str(tmp_path), str(tmp_path), "true", [])
    _, allowed, _ = _sandbox(tmp_path, allow_network=True).wrap(str(tmp_path), str(tmp_path), "true", [])

    assert "--share-net" not in denied
    assert "--share-net" in allowed


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_refuses_without_prlimit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def which(name: str) -> str | None:
        return "/usr/bin/bwrap" if name == "bwrap" else None

    monkeypatch.setattr(shutil, "which", which)

    with pytest.raises(RuntimeError, match="requires prlimit") as excinfo:
        new_platform_sandbox(default_sandbox_config(str(tmp_path)))
    assert "sandbox.mode to off" in str(excinfo.value)


#: The bubblewrap command line is plain data holding POSIX paths, so the tests
#: of its home mounts run on macOS as well as Linux.
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the bwrap command line holds POSIX paths")

#: How many values each option on the sandbox's ``bwrap`` command line takes.
#: Any other option stops parsing with a ``KeyError``, so the mount tests fail
#: when the command line changes shape instead of matching nothing.
BWRAP_OPTION_VALUES: Final[dict[str, int]] = {
    "--die-with-parent": 0,
    "--new-session": 0,
    "--unshare-all": 0,
    "--share-net": 0,
    "--ro-bind": 2,
    "--bind": 2,
    "--tmpfs": 1,
    "--proc": 1,
    "--dev": 1,
    "--dir": 1,
    "--setenv": 2,
    "--chdir": 1,
}

#: The options that decide which host paths a command sees.
HOST_MOUNT_OPTIONS: Final[frozenset[str]] = frozenset({"--ro-bind", "--tmpfs", "--bind"})


def _host_mounts(args: list[str]) -> list[tuple[str, ...]]:
    """The ``--ro-bind``, ``--tmpfs`` and ``--bind`` operations in ``args``, in the order bwrap applies them."""
    operations: list[tuple[str, ...]] = []
    index = 0
    while args[index] != "--":
        values = BWRAP_OPTION_VALUES[args[index]]
        operations.append(tuple(args[index : index + 1 + values]))
        index += 1 + values
    return [operation for operation in operations if operation[0] in HOST_MOUNT_OPTIONS]


def _directory(path: Path) -> str:
    """Create ``path`` and return it resolved, as the sandbox sees it."""
    path.mkdir(parents=True, exist_ok=True)
    return os.path.realpath(path)


def _mounts_hiding(tmp_path: Path, workspace: str, *protected: str) -> list[tuple[str, ...]]:
    """The host mounts for a command in ``workspace`` while ``protected`` homes are hidden."""
    _, args, _ = _sandbox(tmp_path, protected=protected).wrap(workspace, "", "true", [])
    return _host_mounts(args)


@posix_only
def test_sandbox_covers_each_home_after_the_root_and_before_the_workspace(tmp_path: Path) -> None:
    workspace = _directory(tmp_path / "workspace")
    home = _directory(tmp_path / "home")
    account = _directory(tmp_path / "account")

    mounts = _mounts_hiding(tmp_path, workspace, home, account)

    # bubblewrap mounts in order: each tmpfs covers a home in the read-only
    # root, and the workspace bind comes after them so none can cover it.
    assert mounts == [
        ("--ro-bind", "/", "/"),
        ("--tmpfs", home),
        ("--tmpfs", account),
        ("--tmpfs", "/tmp"),
        ("--tmpfs", "/var/tmp"),
        ("--bind", workspace, workspace),
    ]


@posix_only
def test_sandbox_binds_a_workspace_inside_a_home_over_its_tmpfs(tmp_path: Path) -> None:
    home = _directory(tmp_path / "account")
    workspace = _directory(tmp_path / "account" / "projects" / "app")

    _, args, cwd = _sandbox(tmp_path, protected=(home,)).wrap(workspace, "", "true", [])

    assert _host_mounts(args) == [
        ("--ro-bind", "/", "/"),
        ("--tmpfs", home),
        ("--tmpfs", "/tmp"),
        ("--tmpfs", "/var/tmp"),
        ("--bind", workspace, workspace),
    ]
    assert cwd == workspace
    assert args[args.index("--chdir") + 1] == workspace


@posix_only
@pytest.mark.parametrize("inside", [pytest.param("", id="equals"), pytest.param("account", id="contains")])
def test_sandbox_leaves_a_home_within_the_workspace_to_the_workspace(tmp_path: Path, inside: str) -> None:
    workspace = _directory(tmp_path / "workspace")
    home = _directory(Path(workspace, inside))
    other = _directory(tmp_path / "other")

    mounts = _mounts_hiding(tmp_path, workspace, home, other)

    # A home the workspace equals or contains is read and written through the
    # workspace bind; a home outside the workspace is still covered.
    assert mounts == [
        ("--ro-bind", "/", "/"),
        ("--tmpfs", other),
        ("--tmpfs", "/tmp"),
        ("--tmpfs", "/var/tmp"),
        ("--bind", workspace, workspace),
    ]


@posix_only
def test_sandbox_skips_a_home_that_does_not_exist(tmp_path: Path) -> None:
    workspace = _directory(tmp_path / "workspace")
    missing = os.path.join(os.path.realpath(tmp_path), "missing")
    account = _directory(tmp_path / "account")

    mounts = _mounts_hiding(tmp_path, workspace, missing, account)

    # There is nothing to hide, and bubblewrap could not create the mount point
    # in the read-only root: covering it would make every command fail.
    assert ("--tmpfs", missing) not in mounts
    assert ("--tmpfs", account) in mounts


@posix_only
def test_sandbox_covers_a_home_inside_another_home_once(tmp_path: Path) -> None:
    workspace = _directory(tmp_path / "workspace")
    account = _directory(tmp_path / "account")
    home = _directory(tmp_path / "account" / "alternate")

    mounts = _mounts_hiding(tmp_path, workspace, home, account)

    assert mounts == [
        ("--ro-bind", "/", "/"),
        ("--tmpfs", account),
        ("--tmpfs", "/tmp"),
        ("--tmpfs", "/var/tmp"),
        ("--bind", workspace, workspace),
    ]


@posix_only
def test_platform_sandbox_hides_the_users_homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def which(name: str) -> str | None:
        return "/usr/bin/" + name

    monkeypatch.setattr(shutil, "which", which)

    sandbox = new_platform_sandbox(default_sandbox_config(str(tmp_path)))

    assert sandbox.protected == protected_homes()
    assert os.path.realpath(os.environ["HOME"]) in sandbox.protected


def _account_directory(monkeypatch: pytest.MonkeyPatch, directory: str | None) -> None:
    """Make the user database report ``directory`` as the account's home, or no entry at all."""
    import pwd

    def getpwuid(uid: int) -> pwd.struct_passwd:
        if directory is None:
            raise KeyError(uid)
        return pwd.struct_passwd(("user", "x", uid, uid, "", directory, "/bin/sh"))

    monkeypatch.setattr(pwd, "getpwuid", getpwuid)


@posix_only
def test_protected_homes_are_home_and_the_account_home_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _directory(tmp_path / "home-target")
    (tmp_path / "home-link").symlink_to(home)
    account = _directory(tmp_path / "account")
    monkeypatch.setenv("HOME", str(tmp_path / "home-link"))
    _account_directory(monkeypatch, account)

    assert protected_homes() == (home, account)


@posix_only
def test_protected_homes_count_a_directory_reached_both_ways_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _directory(tmp_path / "account")
    (tmp_path / "link").symlink_to(account)
    monkeypatch.setenv("HOME", str(tmp_path / "link"))
    _account_directory(monkeypatch, account)

    assert protected_homes() == (account,)


@posix_only
def test_protected_homes_never_include_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/")
    _account_directory(monkeypatch, "/")

    assert protected_homes() == ()


@posix_only
def test_protected_homes_skip_a_relative_home_and_a_missing_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "relative/home")
    _account_directory(monkeypatch, None)

    assert protected_homes() == ()
