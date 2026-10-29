"""Profile configuration, instruction and provider infrastructure adapters.

Controller constructors inject these facilities into application use cases.
"""

from __future__ import annotations

import dataclasses

from super_agent import llm
from super_agent.app.config import (
    Config,
    firstNonEmpty,
    load_settings_file,
    save_settings_file,
)
from super_agent.app.instructions import Bundle, load as loadInstructions
from super_agent.app.system_prompt import SYSTEM_PROMPT
from super_agent.app.workflows import WorkflowController
from super_agent.application.agents import (
    AgentController as ApplicationAgentController,
    filteredToolRunner as filteredToolRunner,
    routedModel as routedModel,
    withAgentProfile,
)
from super_agent.application.values import AgentProfile as AgentProfile
from super_agent.runtime import (
    PERMISSION_MODE_PLAN,
    ROLE_SYSTEM,
    Message,
    PermissionMode,
    Session,
    valid_permission_mode,
)
from super_agent.runtime.protocol.types import Model

__all__ = [
    "AgentController",
    "AgentProfile",
    "buildAgentProfiles",
    "filteredToolRunner",
    "initialMessages",
    "initialMessagesWithAgent",
    "routedModel",
]


class AgentResourcesAdapter:
    """Model factories, project instructions and settings file access."""

    def __init__(self, path: str) -> None:
        self.path = path

    @property
    def writable(self) -> bool:
        return self.path != ""

    def model(self, provider: str, config: llm.ProviderConfig) -> Model:
        return llm.new_model(provider, config)

    def messages(self, base: str) -> list[Message]:
        messages, _bundle = initialMessages(base)
        return messages

    def save_provider(self, provider: str, api_key: str, model: str) -> llm.ProviderConfig:
        settings = load_settings_file(self.path)
        updated = settings.providers.get(provider)
        if updated is None:
            raise ValueError("provider is not in settings: " + provider)
        updated = dataclasses.replace(updated, api_key=api_key)
        if model != "":
            updated = dataclasses.replace(updated, model=model)
        save_settings_file(
            self.path, dataclasses.replace(settings, providers={**settings.providers, provider: updated})
        )
        return updated


class AgentController(ApplicationAgentController):
    """Compatibility constructor that injects local infrastructure."""

    def __init__(
        self,
        *,
        session: Session,
        model: routedModel,
        profiles: dict[str, AgentProfile],
        providers: dict[str, llm.ProviderConfig],
        workflows: WorkflowController,
        tools: filteredToolRunner | None,
        base: str,
        current: str,
        settings_path: str = "",
    ) -> None:
        facilities = AgentResourcesAdapter(settings_path)
        super().__init__(
            session=session,
            model=model,
            profiles=profiles,
            providers=providers,
            workflows=workflows,
            tools=tools,
            base=base,
            current=current,
            models=facilities,
            instructions=facilities,
            preferences=facilities,
        )


def buildAgentProfiles(cfg: Config, providers: dict[str, llm.ProviderConfig]) -> dict[str, AgentProfile]:
    """Build ``build``, ``plan``, and every configured custom profile.

    ``build`` and ``plan`` are reserved: a custom profile that takes either name
    would be silently shadowed otherwise, so it is an error instead.
    """
    skillPrompt = ""
    if cfg.extensions.skill_prompt != "":
        skillPrompt = "\n\nAvailable skills:\n" + cfg.extensions.skill_prompt
    profiles: dict[str, AgentProfile] = {
        "build": AgentProfile(
            name="build",
            provider=cfg.provider,
            model=cfg.model_config.model,
            prompt="Build mode: inspect, implement, verify, and finish requested changes." + skillPrompt,
            permission_mode=cfg.permission_mode,
        ),
        "plan": AgentProfile(
            name="plan",
            provider=cfg.provider,
            model=cfg.model_config.model,
            prompt="Plan mode: investigate and propose a plan. Do not modify files or run mutating tools."
            + skillPrompt,
            permission_mode=PERMISSION_MODE_PLAN,
        ),
    }
    for rawName, item in cfg.agents.items():
        name = rawName.strip()
        if name == "" or name in ("build", "plan"):
            raise ValueError("custom agent name is empty or reserved: " + name)
        provider = firstNonEmpty(item.provider, cfg.provider)
        providerCfg = providers.get(provider)
        if providerCfg is None:
            raise ValueError("agent " + name + " references unknown provider: " + provider)
        if item.model != "":
            providerCfg = dataclasses.replace(providerCfg, model=item.model)
        mode = PermissionMode(firstNonEmpty(item.permission_mode, str(cfg.permission_mode)))
        if not valid_permission_mode(mode):
            raise ValueError("agent " + name + " has invalid permission mode: " + str(mode))
        profiles[name] = AgentProfile(
            name=name,
            provider=provider,
            model=providerCfg.model,
            prompt=item.prompt.strip() + skillPrompt,
            permission_mode=mode,
            tools=tuple(item.tools),
        )
    return profiles


def initialMessages(cwd: str) -> tuple[list[Message], Bundle]:
    """The built-in prompt plus every instruction layer that applies to ``cwd``.

    The bundle is returned alongside so session metadata can record where the
    instructions came from. It lives here rather than in the session module
    because :func:`initialMessagesWithAgent` is its only caller and the session
    module would otherwise need a mutual import.
    """
    bundle = loadInstructions(cwd)
    content = SYSTEM_PROMPT
    if bundle.content != "":
        content += "\n\n" + bundle.content
    return [Message(role=ROLE_SYSTEM, content=content)], bundle


def initialMessagesWithAgent(cwd: str, profile: AgentProfile) -> tuple[list[Message], Bundle]:
    """:func:`initialMessages` with the active profile's prompt appended.

    The message value is frozen, so a replacement is built rather than mutated in
    place.
    """
    messages, bundle = initialMessages(cwd)
    return withAgentProfile(messages, profile), bundle
