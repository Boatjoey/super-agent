"""The delegation worktree, on every exit path.

The session spec says a delegated worktree is kept so a person can inspect what the
child did. That is a claim about all three ways a delegation ends, not just the
happy one, so each gets its own case: a child that succeeded, one that failed, and
one that was cancelled.

The child itself is scripted here. What is under test is the lifecycle around it —
where it runs, and what survives — not the model protocol a child uses.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import subprocess
from typing import Any

import pytest

from super_agent import llm
from super_agent.app.agents import AgentProfile
from super_agent.app.subagents import subagentTool
from super_agent.runtime import PermissionRules, ToolCall
from super_agent.runtime.protocol.run_context import live_context
from super_agent.tools.sandbox import SANDBOX_MODE_OFF, default_sandbox_config
from super_agent.workspace import new as newWorkspace, new_default_context


def git(repo: str, *arguments: str) -> None:
    """Run one git command, failing the test with git's own output."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git {' '.join(arguments)} failed: {result.stderr}"


@pytest.fixture
def repository_dir(tmp_path: Any) -> str:
    """A repository with one commit, which is all a detached worktree needs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(str(repo), "init", "-q")
    git(str(repo), "config", "user.email", "test@example.com")
    git(str(repo), "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    git(str(repo), "add", "README.md")
    git(str(repo), "commit", "-qm", "one")
    return str(repo)


class ScriptedDelegation(subagentTool):
    """A delegation whose child does one scripted thing, without a model."""

    outcome: str = "succeeded"

    def __init__(self, *, outcome: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.outcome = outcome
        self.childCwd = ""

    async def runChild(
        self,
        ctx: Any,
        profile: AgentProfile,
        prompt: str,
        cwd: str,
        model: Any,
        depth: int,
    ) -> str:
        del ctx, profile, prompt, model, depth
        self.childCwd = cwd
        if self.outcome == "failed":
            raise RuntimeError("the child could not finish")
        if self.outcome == "cancelled":
            raise asyncio.CancelledError()
        return f"Child session: child-1\nWorkspace: {cwd}\n\ndone"


def delegation(repo: str, outcome: str) -> ScriptedDelegation:
    """One delegation bound to ``repo``, with the child scripted by ``outcome``."""
    sandbox = dataclasses.replace(default_sandbox_config(repo), mode=SANDBOX_MODE_OFF)
    return ScriptedDelegation(
        outcome=outcome,
        parent=None,  # type: ignore[arg-type]  # the scripted child never reads it
        repository=None,  # type: ignore[arg-type]
        profiles={"build": AgentProfile(name="build", provider="deepseek", model="test-model")},
        providers={"deepseek": llm.ProviderConfig(base_url="http://127.0.0.1:1/v1", model="test-model")},
        sandbox=sandbox,
        rules=PermissionRules(),
        base=repo,
        workspace=newWorkspace(new_default_context(repo)),
    )


def worktree_of(cwd: str, repo: str) -> str:
    assert cwd != repo, "the child ran in the parent workspace, not a worktree"
    assert cwd.startswith(os.path.join(repo, ".super-agent", "worktrees")), cwd
    return cwd


@pytest.mark.asyncio
async def test_a_finished_delegation_keeps_its_worktree(repository_dir: str) -> None:
    tool = delegation(repository_dir, "succeeded")

    result = await tool.run(live_context(), ToolCall(name="delegate", input='{"prompt": "inspect", "worktree": true}'))

    worktree = worktree_of(tool.childCwd, repository_dir)
    assert os.path.isdir(worktree), "the worktree a person is meant to inspect must still exist"
    assert worktree in result


@pytest.mark.asyncio
async def test_a_failed_delegation_keeps_its_worktree(repository_dir: str) -> None:
    """A failure is exactly when someone wants to look at what happened."""
    tool = delegation(repository_dir, "failed")

    with pytest.raises(RuntimeError, match="could not finish"):
        await tool.run(live_context(), ToolCall(name="delegate", input='{"prompt": "inspect", "worktree": true}'))

    assert os.path.isdir(worktree_of(tool.childCwd, repository_dir))


@pytest.mark.asyncio
async def test_a_cancelled_delegation_keeps_its_worktree(repository_dir: str) -> None:
    tool = delegation(repository_dir, "cancelled")

    with pytest.raises(asyncio.CancelledError):
        await tool.run(live_context(), ToolCall(name="delegate", input='{"prompt": "inspect", "worktree": true}'))

    assert os.path.isdir(worktree_of(tool.childCwd, repository_dir))


@pytest.mark.asyncio
async def test_a_delegation_without_a_worktree_runs_in_the_parent_workspace(repository_dir: str) -> None:
    tool = delegation(repository_dir, "succeeded")

    await tool.run(live_context(), ToolCall(name="delegate", input='{"prompt": "inspect"}'))

    assert tool.childCwd == repository_dir
    assert not os.path.isdir(os.path.join(repository_dir, ".super-agent", "worktrees"))
