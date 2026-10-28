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
from pathlib import Path

import pytest

from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ToolCall
from super_agent.tools import default_registry, default_sandbox_config, sandboxed_registry
from super_agent.tools.commands import command_exit_error, max_output_bytes
from super_agent.tools.sandbox_linux import bubblewrap_sandbox, new_platform_sandbox
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


@pytest.mark.skipif(sys.platform == "linux", reason="Linux has a real strict sandbox")
def test_strict_sandbox_fails_closed_off_linux(tmp_path: Path) -> None:
    """Strict is the default, so an unsupported platform must refuse outright."""
    with pytest.raises(
        RuntimeError,
        match=re.escape("strict sandbox is currently supported only on Linux; set sandbox.mode to off explicitly"),
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


def _namespace_refusal() -> str:
    """Why this kernel cannot start bubblewrap, or an empty string when it can.

    Hosted CI runs inside a container whose policy may forbid unprivileged user
    namespaces. That is an environment limit, not a sandbox regression: probe
    the capability directly and let the integration test skip. A missing binary
    stays a failure, because it is a declared dependency.
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
    refusal = _namespace_refusal()
    if refusal:
        pytest.skip(f"kernel namespaces unavailable: {refusal}")

    probe = await registry.run(live_context(), ToolCall(name="run_command", input='{"command":"printf ready"}'))
    assert probe == "ready"

    inside = workspace / "inside"
    command = f"touch {inside}; touch {outside / 'planted'}"
    # The blocked write is what the sandbox is being asked to produce, so the
    # type is the tool's own: a non-zero exit is a result the model reads, not
    # the ``RuntimeError`` that means the sandbox itself could not run.
    with pytest.raises(command_exit_error):
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


def _sandbox(tmp_path: Path, *, allow_network: bool = False) -> bubblewrap_sandbox:
    config = default_sandbox_config(str(tmp_path))
    config.allow_network = allow_network
    return bubblewrap_sandbox(bwrap="/usr/bin/bwrap", prlimit="/usr/bin/prlimit", config=config)


@pytest.mark.skipif(sys.platform != "linux", reason="the strict sandbox is Linux-only")
def test_sandbox_defaults_an_empty_cwd_to_the_workspace(tmp_path: Path) -> None:
    workspace = os.path.realpath(tmp_path)

    _, args, cwd = _sandbox(tmp_path).wrap(str(tmp_path), "", "true", [])

    assert cwd == workspace
    assert args[args.index("--chdir") + 1] == workspace


@pytest.mark.skipif(sys.platform != "linux", reason="the strict sandbox is Linux-only")
def test_sandbox_refuses_a_cwd_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(RuntimeError, match="outside workspace"):
        _sandbox(workspace).wrap(str(workspace), str(outside), "true", [])


@pytest.mark.skipif(sys.platform != "linux", reason="the strict sandbox is Linux-only")
def test_sandbox_refuses_a_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="workspace is not configured"):
        _sandbox(tmp_path).wrap("", str(tmp_path), "true", [])


@pytest.mark.skipif(sys.platform != "linux", reason="the strict sandbox is Linux-only")
def test_sandbox_shares_the_network_only_when_allowed(tmp_path: Path) -> None:
    _, denied, _ = _sandbox(tmp_path).wrap(str(tmp_path), str(tmp_path), "true", [])
    _, allowed, _ = _sandbox(tmp_path, allow_network=True).wrap(str(tmp_path), str(tmp_path), "true", [])

    assert "--share-net" not in denied
    assert "--share-net" in allowed


@pytest.mark.skipif(sys.platform != "linux", reason="the strict sandbox is Linux-only")
def test_sandbox_refuses_without_prlimit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def which(name: str) -> str | None:
        return "/usr/bin/bwrap" if name == "bwrap" else None

    monkeypatch.setattr(shutil, "which", which)

    with pytest.raises(RuntimeError, match="requires prlimit") as excinfo:
        new_platform_sandbox(default_sandbox_config(str(tmp_path)))
    assert "sandbox.mode to off" in str(excinfo.value)
