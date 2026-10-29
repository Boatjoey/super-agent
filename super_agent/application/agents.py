"""Agent profile switching and provider reconfiguration use cases."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence

from super_agent.application.ports import InstructionSource, ModelResolver, ProviderPreferences
from super_agent.application.values import AgentProfile as AgentProfile
from super_agent.application.workflows import WorkflowController
from super_agent.runtime.protocol.provider import ProviderConfig
from super_agent.runtime.protocol.run_context import RunContext
from super_agent.runtime.protocol.types import (
    ROLE_SYSTEM,
    Message,
    Model,
    ModelResponse,
    StreamChunk,
    ToolCall,
    ToolRunner,
    ToolSpec,
)
from super_agent.runtime.session import Session


class filteredToolRunner:
    """A runner that advertises and accepts only the active profile's tools.

    ``allowed`` is ``None`` when nothing is restricting the tool set. A profile
    that names no tools leaves it ``None`` too, rather than restricting to the
    empty set: "run with the default tools" is the absence of a restriction, not a
    list of zero tools.
    """

    __slots__ = ("_allowed", "_runner")

    def __init__(self, runner: ToolRunner) -> None:
        self._runner = runner
        self._allowed: frozenset[str] | None = None

    def specs(self) -> list[ToolSpec]:
        specs = self._runner.specs()
        if self._allowed is None:
            return specs
        return [spec for spec in specs if spec.name in self._allowed]

    async def run(self, ctx: RunContext, call: ToolCall) -> str:
        if self._allowed is not None and call.name not in self._allowed:
            raise ValueError("tool is not enabled for active agent: " + call.name)
        return await self._runner.run(ctx, call)

    def setAllowed(self, names: Sequence[str]) -> None:
        """Restrict the visible tools, or lift the restriction for an empty list."""
        self._allowed = None if not names else frozenset(names)


class routedModel:
    """The model the engine calls, which :meth:`AgentController.use` swaps.

    The engine holds this one object for its whole life, so a profile switch
    reaches it without rewiring the executor.
    """

    __slots__ = ("_model",)

    def __init__(self, model: Model) -> None:
        self._model = model

    async def next(
        self,
        ctx: RunContext,
        messages: list[Message],
        tools: list[ToolSpec],
        on_stream_chunk: Callable[[StreamChunk], None],
    ) -> ModelResponse:
        return await self._model.next(ctx, messages, tools, on_stream_chunk)

    def set(self, model: Model) -> None:
        """Point the router at a different provider."""
        self._model = model


class AgentController:
    """Lists, switches, and describes the configured agent profiles.

    It also owns provider configuration: setting a provider's key or model writes
    ``settings.json`` and rebuilds the active model at once, so a key entered in
    the interface takes effect without a restart.
    """

    __slots__ = (
        "base",
        "current",
        "instructions",
        "model",
        "models",
        "preferences",
        "profiles",
        "providers",
        "session",
        "tools",
        "workflows",
    )

    def __init__(
        self,
        *,
        session: Session,
        model: routedModel,
        profiles: dict[str, AgentProfile],
        providers: dict[str, ProviderConfig],
        workflows: WorkflowController,
        tools: filteredToolRunner | None,
        base: str,
        current: str,
        models: ModelResolver,
        instructions: InstructionSource,
        preferences: ProviderPreferences,
    ) -> None:
        self.models = models
        self.instructions = instructions
        self.preferences = preferences
        self.session = session
        self.model = model
        self.profiles = profiles
        self.providers = providers
        self.workflows = workflows
        self.tools = tools
        self.base = base
        self.current = current

    # --- workflow delegation -------------------------------------------------

    async def git_diff(self, ctx: RunContext) -> str:
        return await self.workflows.git_diff(ctx)

    async def git_status(self, ctx: RunContext) -> str:
        return await self.workflows.git_status(ctx)

    async def diagnostics(self, ctx: RunContext, path: str) -> str:
        return await self.workflows.diagnostics(ctx, path)

    async def run_hook(self, ctx: RunContext, event: str) -> None:
        await self.workflows.run_hook(ctx, event)

    async def run_hooks(self, ctx: RunContext, *events: str) -> None:
        await self.workflows.run_hooks(ctx, *events)

    def custom_commands(self) -> list[str]:
        return self.workflows.custom_commands()

    def skills(self) -> list[str]:
        return self.workflows.skills()

    def plugins(self) -> list[str]:
        return self.workflows.plugins()

    def expand_command(self, name: str, arguments: str) -> str:
        return self.workflows.expand_command(name, arguments)

    # --- the profile table ---------------------------------------------------

    def list(self) -> list[AgentProfile]:
        """Every profile, ordered by name."""
        return sorted(self.profiles.values(), key=lambda profile: profile.name)

    def active_profile(self) -> AgentProfile:
        """The active profile, or a zero one when the name is unknown."""
        return self.profiles.get(self.current, AgentProfile())

    async def use(self, name: str) -> None:
        """Switch to ``name``, replacing the context, model, and tool set.

        The conversation is replaced before the permission mode changes, so the
        new mode is never in force over the old conversation.
        """
        profile = self.profiles.get(name)
        if profile is None:
            raise ValueError("unknown agent: " + name)
        config = self.providers[profile.provider]
        if profile.model != "":
            config = dataclasses.replace(config, model=profile.model)
        model = self.models.model(profile.provider, config)
        messages = withAgentProfile(self.instructions.messages(self.base), profile)
        memories = self.session.memories()
        if memories:
            messages = [
                *messages,
                Message(role=ROLE_SYSTEM, content="Cross-session memory:\n- " + "\n- ".join(memories)),
            ]
        await self.session.replace_conversation(messages)
        await self.session.set_permission_mode(profile.permission_mode)
        self.model.set(model)
        if self.tools is not None:
            self.tools.setAllowed(profile.tools)
        self.current = name

    # --- provider configuration ---------------------------------------------

    def provider_config(self, provider: str) -> ProviderConfig:
        """The resolved configuration for ``provider``, credential included."""
        return self.providers.get(provider, ProviderConfig())

    async def configure_provider(self, provider: str, api_key: str, model: str = "") -> None:
        """Set a provider's credential (and optionally model), persisting both.

        The write goes to ``settings.json`` first so a restart keeps the key, then
        the in-memory provider table is updated and the active model rebuilt when
        the configured provider is the one in use. The model is rebuilt rather
        than the session being restarted, so a key entered in the interface takes
        effect on the very next turn.
        """
        if provider not in self.providers:
            raise ValueError("unknown provider: " + provider)
        if not self.preferences.writable:
            raise ValueError("provider configuration is not writable: no settings path")
        # Persist first: a key that does not survive the restart is a trap.
        updated = self.preferences.save_provider(provider, api_key, model)
        # Rebuild the in-memory table and the active model. Profiles whose
        # provider is the one just configured follow the new model name, so the
        # status bar and the next switch do not show a stale value.
        self.providers[provider] = updated
        if model != "":
            self.profiles = {
                name: (dataclasses.replace(profile, model=model) if profile.provider == provider else profile)
                for name, profile in self.profiles.items()
            }
        profile = self.active_profile()
        if profile.provider == provider:
            config = self.providers[provider]
            if profile.model != "":
                config = dataclasses.replace(config, model=profile.model)
            self.model.set(self.models.model(provider, config))


def withAgentProfile(messages: list[Message], profile: AgentProfile) -> list[Message]:
    """Append the selected profile to the initial system context."""
    messages = list(messages)
    if profile.prompt != "":
        first = messages[0]
        messages[0] = dataclasses.replace(
            first,
            content=first.content + "\n\nActive agent profile: " + profile.name + "\n" + profile.prompt,
        )
    return messages
