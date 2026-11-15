"""Building one session: the composition root's constructor.

Everything the runtime needs is created here and handed over exactly once; after
:func:`new_session_with_extensions` returns, the session owns the extension and
language-server processes, the telemetry sink, and the durable store.

Three shapes are worth naming:

* the constructor is a coroutine, since connecting MCP and LSP servers is;
* an asynchronous ``close`` is adapted to the session's synchronous
  :class:`~super_agent.runtime.session.Closer` port by :class:`AsyncCloser`, whose
  coroutine :func:`wait_pending_closers` awaits after ``session.close()``;
* the tool hooks are a runner wrapping the registry (:class:`ToolHooks`) rather
  than a registry observer, because the observer port is synchronous and a hook
  runs a command.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
from collections.abc import Callable, Coroutine
from typing import Any

from super_agent import llm, store, tools
from super_agent.app.agents import AgentController, build_agent_profiles, initial_messages_with_agent
from super_agent.app.config import (
    Config,
    first_non_empty,
    instruction_source_paths,
    settings_map,
    settings_path,
)
from super_agent.app.mcp import MCPController, new_mcp_controller
from super_agent.app.memory import MemoryController, open_memory
from super_agent.app.subagents import SubagentTool
from super_agent.application.agents import FilteredToolRunner, RoutedModel
from super_agent.application.workflows import ToolHooks, WorkflowController
from super_agent.errors import JoinedError
from super_agent.runtime.engine import new_engine_with_executor_and_policy
from super_agent.runtime.execution import DefaultScheduledActionExecutor, new_policy
from super_agent.runtime.protocol.run_context import live_context
from super_agent.runtime.protocol.types import ToolRunner
from super_agent.runtime.session import Metadata, Session, create_persistent_session
from super_agent.runtime.session.memory import with_memory_context
from super_agent.store import telemetry
from super_agent.tools import lsp as lsptools, mcp as mcptools
from super_agent.workspace import Context, new as new_workspace

__all__ = [
    "AsyncCloser",
    "CloserFunc",
    "context_for_config",
    "new_session",
    "new_session_with_extensions",
    "new_session_with_mcp",
    "wait_pending_closers",
]


async def new_session(cfg: Config) -> Session:
    """The ordinary entry point: a session, with its MCP controller discarded."""
    session, _mcp = await new_session_with_mcp(cfg)
    return session


async def new_session_with_mcp(cfg: Config) -> tuple[Session, MCPController | None]:
    """A session and its MCP controller, without the agent controller."""
    session, mcp, _agents, _memory = await new_session_with_extensions(cfg)
    return session, mcp


async def new_session_with_extensions(
    cfg: Config,
) -> tuple[Session, MCPController | None, AgentController, MemoryController]:
    """Build the runtime, the tools, and the controllers for one session.

    The model is built from the *resolved* provider configuration — ``cfg.model_config``
    — and not from the raw ``cfg.provider_configs`` entry. That entry still holds
    the template placeholder whenever the credential came from the environment,
    and sending ``sk-...`` as a bearer token is the bug this port fixes.
    """
    workspace_context = context_for_config(cfg)
    cwd = workspace_context.get_cwd()
    config_root = first_non_empty(cfg.config_root, cfg.project.root, cwd)
    workspace_runtime = new_workspace(workspace_context)
    cfg.sandbox.workspace = workspace_context.get_primary_root()
    telemetry.configure(cfg.telemetry_path)
    telemetry_owned = True
    extension: mcptools.Manager | None = None
    lsp_closer: lsptools.Manager | None = None
    try:
        providers = dict(cfg.provider_configs)
        if not providers:
            providers = {cfg.provider: cfg.model_config}
        else:
            # The selected provider's entry is replaced by the resolved one, so a
            # profile naming the default provider gets the resolved credential and
            # a profile naming another provider still gets its own entry.
            providers[cfg.provider] = cfg.model_config
        profiles = build_agent_profiles(cfg, providers)
        agent_name = first_non_empty(cfg.agent, "build")
        profile = profiles.get(agent_name)
        if profile is None:
            raise ValueError("unknown configured agent: " + agent_name)
        provider_config = providers[profile.provider]
        if profile.model != "":
            provider_config = dataclasses.replace(provider_config, model=profile.model)
        model = llm.new_model(profile.provider, provider_config)
        router = RoutedModel(model)
        tool_runner: ToolRunner
        registry: tools.Registry | None = None
        hooks: ToolHooks | None = None
        controller: MCPController | None = None
        tool_filter: FilteredToolRunner | None = None
        if cfg.no_tools:
            tool_runner = tools.NoTools()
        else:
            registry = tools.sandboxed_registry(cfg.sandbox, workspace_runtime)
            manager = await mcptools.connect(live_context(), cfg.mcp_servers)
            try:
                registry.add(*manager.tools())
            except BaseException:
                with contextlib.suppress(Exception):
                    await manager.close()
                raise
            controller = new_mcp_controller(manager, registry, settings_path(), cwd, settings_map(cfg.mcp_servers))
            # The runtime session owns extension process lifetime after creation.
            extension = manager
            if cfg.lsp_servers:
                lsp_manager = await lsptools.connect(live_context(), workspace_runtime, cfg.lsp_servers)
                try:
                    for lsp_tool in lsp_manager.tools():
                        registry.add(lsp_tool)
                except BaseException:
                    with contextlib.suppress(Exception):
                        await lsp_manager.close()
                    raise
                lsp_closer = lsp_manager
            hooks = ToolHooks(registry)
            tool_filter = FilteredToolRunner(hooks)
            tool_filter.set_allowed(profile.tools)
            tool_runner = tool_filter
        initial, bundle = initial_messages_with_agent(config_root, profile)
        st = store.open_default()
        repository = store.new_repository(st)
        # The memory is chosen here, once: the settings name the backend and the
        # switch, and everything below — this session, the delegated children,
        # the front ends — uses that one port.
        memory = open_memory(cfg.memory, st)
        initial = with_memory_context(initial, memory.load())
        engine = new_engine_with_executor_and_policy(
            DefaultScheduledActionExecutor(router, tool_runner),
            new_policy(profile.permission_mode, cfg.permission_rules),
            initial,
        )
        await engine.ready()
        session = create_persistent_session(
            engine,
            repository,
            workspace_runtime,
            Metadata(
                provider=profile.provider,
                model=profile.model,
                cwd=cwd,
                title=os.path.basename(cwd),
                instruction_sources=instruction_source_paths(bundle),
                project_id=cfg.project.id,
                config_root=config_root,
            ),
            initial,
            memory=memory,
        )
        if registry is not None and hooks is not None:
            registry.set_checkpoint_callback(session.checkpoint)
            delegate = SubagentTool(
                parent=session,
                repository=repository,
                profiles=profiles,
                providers=providers,
                sandbox=cfg.sandbox,
                rules=cfg.permission_rules,
                base=cwd,
                workspace=workspace_runtime,
                memory=memory,
            )
            try:
                registry.add(delegate)
            except BaseException:
                with contextlib.suppress(Exception):
                    await session.close()
                raise
        session.configure_permissions(profile.permission_mode, cfg.permission_rules)
        if extension is not None:
            session.add_closer(AsyncCloser(extension.close))
            extension = None
        if lsp_closer is not None:
            session.add_closer(AsyncCloser(lsp_closer.close))
            lsp_closer = None
        session.add_closer(CloserFunc(telemetry.close))
        telemetry_owned = False
        workflows = WorkflowController(registry=hooks, extensions=cfg.extensions)
        if hooks is not None:
            hooks.set_workflows(workflows)
        try:
            await workflows.run_hooks(live_context(), "session_start", "startup")
        except BaseException:
            with contextlib.suppress(Exception):
                await session.close()
            raise
        agents = AgentController(
            session=session,
            model=router,
            profiles=profiles,
            providers=providers,
            workflows=workflows,
            tools=tool_filter,
            base=cwd,
            current=profile.name,
            settings_path=settings_path(),
        )
        memories = MemoryController(memory, session, settings_path())
        return session, controller, agents, memories
    except BaseException:
        # The cleanup path, which runs only while ownership was never handed over.
        # Once the session owns a closer the field it was read from is cleared, so
        # nothing is closed twice.
        if extension is not None:
            with contextlib.suppress(Exception):
                await extension.close()
        if lsp_closer is not None:
            with contextlib.suppress(Exception):
                await lsp_closer.close()
        if telemetry_owned:
            telemetry.close()
        raise


def context_for_config(cfg: Config) -> Context:
    """The workspace context, which a bare :class:`Config` may not carry."""
    if cfg.workspace is not None:
        return cfg.workspace
    raise ValueError("workspace context is required")


class CloserFunc:
    """A plain callable adapted to the session's :class:`Closer` port.

    The telemetry sink closes synchronously and needs no adapter beyond this one.
    """

    __slots__ = ("_close",)

    def __init__(self, close: Callable[[], None]) -> None:
        self._close = close

    def close(self) -> None:
        self._close()


#: The closes :class:`AsyncCloser` scheduled that nothing has awaited yet.
_pending_closes: list[asyncio.Task[None]] = []


class AsyncCloser:
    """An asynchronous ``close`` adapted to the session's synchronous port.

    Each extension process hands the session a closer that wants to close
    asynchronously — killing a child and waiting for it — while the session's close
    loop calls each closer synchronously. The coroutine is therefore scheduled on
    the running loop and kept, and :func:`wait_pending_closers` awaits it once
    ``session.close()`` has returned.
    """

    __slots__ = ("_close",)

    def __init__(self, close: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self._close = close

    def close(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop is running, so nothing can be scheduled: run it here.
            asyncio.run(self._close())
            return
        _pending_closes.append(loop.create_task(self._close()))


async def wait_pending_closers() -> None:
    """Await the closes :class:`AsyncCloser` scheduled, joining the failures."""
    failures: list[BaseException] = []
    while _pending_closes:
        task = _pending_closes.pop()
        try:
            await task
        except Exception as error:
            failures.append(error)
    if failures:
        raise JoinedError(*failures)
