"""The ``delegate`` tool: running a task in a child agent.

A delegation creates a real persistent child session with its own workspace, its
own tool registry, and its own engine, runs one turn, and returns the child's
final assistant message to the parent call.

Three rules are kept exactly:

* the recursion depth is carried on the run context, and a fourth level is
  refused;
* a delegated worktree is created through the *sandboxed* command tool, under
  ``<workspace>/.super-agent/worktrees/<nano>-<seq>`` — the hyphenated spelling,
  which is what distinguishes it from the configuration directories — and is kept
  afterwards, because the point of the copy is that a person can inspect what the
  child did;
* a sub-session auto-denies every approval request, so a delegation can never
  block on a prompt nobody is watching.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import time
from collections.abc import Iterator

from super_agent import jsonutil, llm, tools
from super_agent.app.agents import AgentProfile, filteredToolRunner, initialMessagesWithAgent
from super_agent.app.config import instructionSourcePaths
from super_agent.application.delegation import (
    Delegation,
    finalAssistantContent as finalAssistantContent,
    maxSubagentDepth as maxSubagentDepth,
    subagentDepthKey as subagentDepthKey,
    subagentInput as subagentInput,
    truncate as truncate,
)
from super_agent.runtime import (
    DefaultScheduledActionExecutor,
    Metadata,
    PermissionRules,
    Session,
    ToolCall,
    ToolSpec,
    create_persistent_session,
    new_engine_with_executor_and_policy,
    new_policy,
)
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import Model
from super_agent.runtime.session.memory import Memory, withMemoryContext
from super_agent.runtime.session.repository import Repository
from super_agent.tools.sandbox import SandboxConfig
from super_agent.workspace import Workspace, new as newWorkspace, new_default_context

__all__ = [
    "finalAssistantContent",
    "maxSubagentDepth",
    "subagentDepthKey",
    "subagentInput",
    "subagentTool",
    "truncate",
]


@dataclasses.dataclass(slots=True)
class subagentTool:
    """One level of delegation, bound to the parent session."""

    parent: Session
    repository: Repository
    profiles: dict[str, AgentProfile]
    providers: dict[str, llm.ProviderConfig]
    sandbox: SandboxConfig
    rules: PermissionRules
    base: str
    workspace: Workspace | None
    #: The same memory port the parent session holds, so a child inherits the
    #: lines and the switch rather than a copy of them.
    memory: Memory | None = None
    sequence: Iterator[int] = dataclasses.field(default_factory=lambda: itertools.count(1))

    def specs(self) -> list[ToolSpec]:
        return [self.spec()]

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="delegate",
            description="Run a task in a child agent and return its final result.",
            risky=True,
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "agent": {"type": "string"},
                    "worktree": {"type": "boolean"},
                },
                "required": ["prompt"],
            },
        )

    async def run(self, ctx: RunContext, call: ToolCall) -> str:
        return await Delegation(self.profiles, self.base, self).run(ctx, call)

    def model(self, profile: AgentProfile) -> Model:
        config = self.providers[profile.provider]
        if profile.model:
            config = dataclasses.replace(config, model=profile.model)
        return llm.new_model(profile.provider, config)

    async def worktree(self, ctx: RunContext) -> str:
        return await self.createWorktree(ctx)

    async def child(self, profile: AgentProfile, prompt: str, cwd: str, model: Model) -> Session:
        """Build the child session, run one turn, and return its final result."""
        initial, bundle = initialMessagesWithAgent(cwd, profile)
        memory = self.memory
        if memory is not None:
            initial = withMemoryContext(initial, memory.load())
        sandbox = dataclasses.replace(self.sandbox, workspace=cwd)
        childWorkspace = new_default_context(cwd)
        childWorkspaceRuntime = newWorkspace(childWorkspace)
        registry = tools.sandboxed_registry(sandbox, childWorkspaceRuntime)
        childDelegate = dataclasses.replace(self, base=cwd, workspace=childWorkspaceRuntime)
        registry.add(childDelegate)
        filtered = filteredToolRunner(registry)
        filtered.setAllowed(profile.tools)
        engine = new_engine_with_executor_and_policy(
            DefaultScheduledActionExecutor(model, filtered),
            new_policy(profile.permission_mode, self.rules),
            initial,
        )
        await engine.ready()
        parentMeta = self.parent.metadata()
        child = create_persistent_session(
            engine,
            self.repository,
            childWorkspaceRuntime,
            Metadata(
                parent_id=parentMeta.id,
                provider=profile.provider,
                model=profile.model,
                cwd=cwd,
                title="subagent: " + truncate(prompt, 48),
                instruction_sources=instructionSourcePaths(bundle),
                project_id=parentMeta.project_id,
                config_root=cwd,
            ),
            initial,
            memory=memory,
        )
        return child

    async def createWorktree(self, ctx: RunContext) -> str:
        """Create a detached worktree through the sandboxed ``run_command`` tool."""
        if self.workspace is None:
            raise ValueError("workspace context is required")
        identifier = f"{time.time_ns()}-{next(self.sequence)}"
        path = self.workspace.resolve_path(os.path.join(".super-agent", "worktrees", identifier))
        if not self.workspace.can_write(path):
            raise ValueError("worktree path is outside writable workspace roots")
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        command = "git worktree add --detach " + json.dumps(path) + " HEAD"
        payload = jsonutil.dumps({"command": command, "cwd": self.base, "timeout_seconds": 60})
        registry = tools.sandboxed_registry(self.sandbox, self.workspace)
        try:
            await registry.run(ctx, ToolCall(name="run_command", input=payload))
        except Exception as error:
            raise ValueError(f"create worktree: {error}") from error
        return path
