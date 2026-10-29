"""Extension workflows: hooks, custom commands, and the read-only repository queries.

A hook runs a shell command through ``tools.Registry.run_direct``, never through
``run``: ``run`` is what triggers the pre-tool and post-tool hooks, so a hook that
reached it would re-enter the observer that invoked it.
"""

from __future__ import annotations

from typing import Protocol

from super_agent import jsonutil
from super_agent.application.values import Extensions
from super_agent.errors import JoinedError
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import ToolCall, ToolSpec

__all__ = ["Runner", "WorkflowController"]

#: The empty JSON object used when a call takes no arguments.
NO_ARGUMENTS = "{}"


class Runner(Protocol):
    """The tool runner the workflow queries reach.

    Declared here rather than imported so this module does not depend on the
    composition code that wraps the registry with the hooks.
    """

    def specs(self) -> list[ToolSpec]: ...

    async def run(self, ctx: RunContext, call: ToolCall) -> str: ...

    async def run_direct(self, ctx: RunContext, call: ToolCall) -> str: ...


class WorkflowController:
    """Hooks, custom commands, git queries, and language-server diagnostics."""

    __slots__ = ("extensions", "registry")

    def __init__(self, registry: Runner | None, extensions: Extensions) -> None:
        self.registry = registry
        self.extensions = extensions

    async def git_diff(self, ctx: RunContext) -> str:
        """The working tree's diff."""
        if self.registry is None:
            raise ValueError("workflow tools are unavailable")
        return await self.registry.run(ctx, ToolCall(name="git_diff", input=NO_ARGUMENTS))

    async def git_status(self, ctx: RunContext) -> str:
        """The working tree's short status."""
        if self.registry is None:
            raise ValueError("workflow tools are unavailable")
        return await self.registry.run(ctx, ToolCall(name="git_status", input=NO_ARGUMENTS))

    async def diagnostics(self, ctx: RunContext, path: str) -> str:
        """The language server's diagnostics for one file."""
        if self.registry is None:
            raise ValueError("workflow tools are unavailable")
        return await self.registry.run(ctx, ToolCall(name="lsp_diagnostics", input=jsonutil.dumps({"path": path})))

    async def run_hook(self, ctx: RunContext, event: str) -> None:
        """Run every command configured for ``event``, in order."""
        for command in self.extensions.hooks.get(event, ()):
            if self.registry is None:
                raise ValueError("hooks require tools")
            payload = jsonutil.dumps({"command": command})
            await self.registry.run_direct(ctx, ToolCall(name="run_command", input=payload))

    async def run_hooks(self, ctx: RunContext, *events: str) -> None:
        """Run several events' hooks, joining every failure into one error.

        A failure never stops the next event: the hooks are independent, and the
        caller wants to know about all of them.
        """
        failures: list[BaseException] = []
        for event in events:
            try:
                await self.run_hook(ctx, event)
            except Exception as error:
                failures.append(error)
        if failures:
            raise JoinedError(*failures)

    def custom_commands(self) -> list[str]:
        """Every custom command name, sorted."""
        return sorted(self.extensions.commands)

    def skills(self) -> list[str]:
        """Every discovered skill name."""
        return list(self.extensions.skills)

    def plugins(self) -> list[str]:
        """Every discovered plugin name."""
        return list(self.extensions.plugins)

    def expand_command(self, name: str, arguments: str) -> str:
        """Substitute ``$ARGUMENTS``, or append the arguments when there is none."""
        template = self.extensions.commands.get(name)
        if template is None:
            raise ValueError("unknown custom command: " + name)
        if "$ARGUMENTS" in template:
            return template.replace("$ARGUMENTS", arguments)
        if arguments.strip() != "":
            template += "\n\nArguments: " + arguments
        return template


class toolHooks:
    """Runs the ``pre_tool`` and ``post_tool`` extension hooks around a call.

    The observer port is a synchronous callable while a hook runs a command, which
    is asynchronous, so the ordering the observer exists to guarantee is kept by
    wrapping the runner instead: the pre-hook finishes before the tool starts, a
    pre-hook failure
    aborts the call, and a post-hook failure is appended to the output rather than
    turning a finished call into a failed one. Hooks run through ``run_direct``, so
    a hook cannot re-enter the hooks that invoked it.
    """

    __slots__ = ("_registry", "_workflows")

    def __init__(self, registry: Runner) -> None:
        self._registry = registry
        self._workflows: WorkflowController | None = None

    def set_workflows(self, workflows: WorkflowController) -> None:
        """Install the controller the hooks run through.

        Set after construction because the controller reaches these hooks back for
        its own queries, so the pair is a cycle.
        """
        self._workflows = workflows

    def specs(self) -> list[ToolSpec]:
        return self._registry.specs()

    async def run(self, ctx: RunContext, call: ToolCall) -> str:
        """Run ``call`` between the pre-tool and post-tool hooks."""
        workflows = self._workflows
        if workflows is not None:
            await workflows.run_hook(ctx, "pre_tool")
        result = ""
        error: BaseException | None = None
        try:
            result = await self._registry.run_direct(ctx, call)
        except BaseException as failure:
            error = failure
        if workflows is not None:
            try:
                await workflows.run_hook(ctx, "post_tool")
            except Exception as hookError:
                if error is None:
                    result += "\n[post_tool hook failed: " + str(hookError) + "]"
        if error is not None:
            raise error
        return result

    async def run_direct(self, ctx: RunContext, call: ToolCall) -> str:
        """Run ``call`` without hooks; hooks use this to avoid recursing."""
        return await self._registry.run_direct(ctx, call)
