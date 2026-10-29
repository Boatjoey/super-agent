"""Delegation validation, depth limit, approval policy and result settlement."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from collections.abc import Sequence
from typing import Final

from super_agent import jsonutil
from super_agent.application.ports import DelegationEnvironment
from super_agent.application.values import AgentProfile
from super_agent.jsonutil import json_field
from super_agent.runtime.machine import DENY_APPROVAL, ApprovalDecision
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import ROLE_ASSISTANT, Message, Model, ToolCall
from super_agent.runtime.session import (
    ApprovalsClosed,
    NotificationsClosed,
    Session,
    SessionNotification,
    ToolApprovalRequested,
)

#: How many levels of delegation are allowed. The first child runs at depth 1.
maxSubagentDepth: Final[int] = 3

#: The run-context key carrying the current depth. An object identity is the
#: private-type equivalent.
subagentDepthKey: Final[object] = object()


@dataclasses.dataclass(frozen=True, slots=True)
class subagentInput:
    """The ``delegate`` tool's arguments."""

    prompt: str = dataclasses.field(default="", metadata=json_field(name="prompt"))
    agent: str = dataclasses.field(default="", metadata=json_field(name="agent"))
    worktree: bool = dataclasses.field(default=False, metadata=json_field(name="worktree"))


class Delegation:
    def __init__(self, profiles: dict[str, AgentProfile], base: str, environment: DelegationEnvironment) -> None:
        self.profiles = profiles
        self.base = base
        self.environment = environment

    async def run(self, ctx: RunContext, call: ToolCall) -> str:
        """Run one delegation and return the child's final result."""
        rawDepth = ctx.value(subagentDepthKey)
        depth = rawDepth if isinstance(rawDepth, int) else 0
        if depth >= maxSubagentDepth:
            raise ValueError("maximum subagent depth reached")
        try:
            input = jsonutil.loads(call.input, subagentInput)
        except (ValueError, TypeError) as error:
            raise ValueError(f"decode delegate input: {error}") from error
        prompt = input.prompt.strip()
        if prompt == "":
            raise ValueError("delegate prompt is required")
        name = input.agent.strip() or "build"
        profile = self.profiles.get(name)
        if profile is None:
            raise ValueError("unknown subagent profile: " + name)
        model = self.environment.model(profile)
        cwd = self.base
        if input.worktree:
            cwd = await self.environment.worktree(ctx)
        # The worktree is not removed, on any path: the result names it precisely
        # so the work can be inspected afterwards, and deleting it would take the
        # evidence away. Cleanup is the user's call, not the delegation's.
        return await self.runChild(ctx, profile, prompt, cwd, model, depth)

    async def runChild(
        self, ctx: RunContext, profile: AgentProfile, prompt: str, cwd: str, model: Model, depth: int
    ) -> str:
        """Build the child session, run one turn, and return its final result."""
        child = await self.environment.child(profile, prompt, cwd, model)
        result = ""
        try:
            await self.runTurn(ctx, child, prompt, depth)
            result = finalAssistantContent(child.snapshot().messages)
        finally:
            with contextlib.suppress(Exception):
                await child.close()
        if result == "":
            raise ValueError("subagent returned no assistant result")
        return f"Child session: {child.metadata().id}\nWorkspace: {cwd}\n\n{result}"

    async def runTurn(self, ctx: RunContext, child: Session, prompt: str, depth: int) -> None:
        """Run one child turn, denying every approval it asks for.

        The denial runs on its own task while the turn blocks, so the same
        decoupling holds; the task is cancelled once the turn ends so nothing
        outlives the delegation.
        """
        notifications: asyncio.Queue[SessionNotification] = asyncio.Queue(maxsize=100)
        approvals: asyncio.Queue[ApprovalDecision | ApprovalsClosed] = asyncio.Queue(maxsize=1)

        async def denyApprovals() -> None:
            while True:
                notification = await notifications.get()
                if isinstance(notification, NotificationsClosed):
                    return
                if isinstance(notification, ToolApprovalRequested):
                    await approvals.put(DENY_APPROVAL)

        denier = asyncio.create_task(denyApprovals())
        try:
            await child.run_turn(ctx.with_value(subagentDepthKey, depth + 1), prompt, notifications, approvals)
        finally:
            denier.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await denier


def finalAssistantContent(messages: Sequence[Message]) -> str:
    """The newest assistant message's text, or the empty string."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == ROLE_ASSISTANT:
            return messages[index].content.strip()
    return ""


def truncate(value: str, limit: int) -> str:
    """``value`` cut to ``limit`` characters, with an ellipsis when it was cut."""
    if len(value) <= limit:
        return value
    return value[:limit] + "\u2026"
