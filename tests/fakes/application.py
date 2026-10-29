"""In-memory outbound facilities for application transaction tests."""

from collections.abc import Sequence

from super_agent.application.mcp import MCPServerSummary
from super_agent.application.values import AgentProfile, MCPServerSettings
from super_agent.runtime.engine import new_engine_with_executor
from super_agent.runtime.execution import DefaultScheduledActionExecutor
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import Model, ToolRunner, ToolSpec
from super_agent.runtime.session import Session, new_session
from tests.fakes.execution import FakeToolRunner


class MCPBackend:
    def __init__(self, *, fail_install: bool = False, fail_save: bool = False) -> None:
        self.fail_install = fail_install
        self.fail_save = fail_save
        self.connected: set[str] = set()
        self.installed: set[str] = set()
        self.saved: dict[str, MCPServerSettings] = {}
        self.events: list[str] = []

    def servers(self) -> list[MCPServerSummary]:
        return [MCPServerSummary(name=name, tools=(name,)) for name in sorted(self.connected)]

    async def connect(self, ctx: RunContext, name: str, settings: MCPServerSettings) -> Sequence[ToolRunner]:
        self.events.append("connect")
        self.connected.add(name)
        return [FakeToolRunner(specs=[ToolSpec(name=name)])]

    async def disconnect(self, name: str) -> Sequence[str]:
        self.events.append("disconnect")
        self.connected.remove(name)
        return [name]

    def install(self, items: Sequence[ToolRunner]) -> None:
        self.events.append("install")
        if self.fail_install:
            raise ValueError("catalog conflict")
        self.installed.update(spec.name for item in items for spec in item.specs())

    def uninstall(self, names: Sequence[str]) -> None:
        self.events.append("uninstall")
        self.installed.difference_update(names)

    async def restart(self, ctx: RunContext, name: str) -> None:
        self.events.append("restart")

    def save(self, name: str, server: MCPServerSettings | None) -> None:
        self.events.append("save")
        if self.fail_save:
            raise OSError("settings unavailable")
        if server is None:
            self.saved.pop(name, None)
        else:
            self.saved[name] = server


class DelegationEnvironment:
    def __init__(self, model: Model) -> None:
        self.model_instance = model
        self.tools = FakeToolRunner(specs=[ToolSpec(name="unsafe", risky=True)])
        self.children: list[Session] = []
        self.closed = 0
        self.calls: list[str] = []

    def model(self, profile: AgentProfile) -> Model:
        self.calls.append("model")
        return self.model_instance

    async def worktree(self, ctx: RunContext) -> str:
        self.calls.append("worktree")
        return "/child-worktree"

    async def child(self, profile: AgentProfile, prompt: str, cwd: str, model: Model) -> Session:
        self.calls.append("child")
        engine = new_engine_with_executor(DefaultScheduledActionExecutor(model, self.tools), None)
        await engine.ready()
        session = new_session(engine)
        session.add_closer(self)
        self.children.append(session)
        return session

    def close(self) -> None:
        self.closed += 1
