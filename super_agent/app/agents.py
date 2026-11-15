"""Profile configuration, instruction and provider infrastructure adapters.

Controller constructors inject these facilities into application use cases.
"""

from __future__ import annotations

import dataclasses

from super_agent import llm
from super_agent.app.config import (
    Config,
    first_non_empty,
    load_settings_file,
    save_settings_file,
)
from super_agent.app.instructions import Bundle, load as load_instructions
from super_agent.app.system_prompt import SYSTEM_PROMPT
from super_agent.application.agents import (
    AgentController as ApplicationAgentController,
    FilteredToolRunner,
    RoutedModel,
    with_agent_profile,
)
from super_agent.application.values import AgentProfile
from super_agent.application.workflows import WorkflowController
from super_agent.runtime.execution import PERMISSION_MODE_PLAN, PermissionMode, valid_permission_mode
from super_agent.runtime.protocol.types import ROLE_SYSTEM, Message, Model
from super_agent.runtime.session import Session

__all__ = [
    "AgentController",
    "build_agent_profiles",
    "initial_messages",
    "initial_messages_with_agent",
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
        messages, _bundle = initial_messages(base)
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
        model: RoutedModel,
        profiles: dict[str, AgentProfile],
        providers: dict[str, llm.ProviderConfig],
        workflows: WorkflowController,
        tools: FilteredToolRunner | None,
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


def build_agent_profiles(cfg: Config, providers: dict[str, llm.ProviderConfig]) -> dict[str, AgentProfile]:
    """Build ``build``, ``plan``, and every configured custom profile.

    ``build`` and ``plan`` are reserved: a custom profile that takes either name
    would be silently shadowed otherwise, so it is an error instead.
    """
    skill_prompt = ""
    if cfg.extensions.skill_prompt != "":
        skill_prompt = "\n\nAvailable skills:\n" + cfg.extensions.skill_prompt
    profiles: dict[str, AgentProfile] = {
        "build": AgentProfile(
            name="build",
            provider=cfg.provider,
            model=cfg.model_config.model,
            prompt="Build mode: inspect, implement, verify, and finish requested changes." + skill_prompt,
            permission_mode=cfg.permission_mode,
        ),
        "plan": AgentProfile(
            name="plan",
            provider=cfg.provider,
            model=cfg.model_config.model,
            prompt="Plan mode: investigate and propose a plan. Do not modify files or run mutating tools."
            + skill_prompt,
            permission_mode=PERMISSION_MODE_PLAN,
        ),
    }
    for raw_name, item in cfg.agents.items():
        name = raw_name.strip()
        if name == "" or name in ("build", "plan"):
            raise ValueError("custom agent name is empty or reserved: " + name)
        provider = first_non_empty(item.provider, cfg.provider)
        provider_cfg = providers.get(provider)
        if provider_cfg is None:
            raise ValueError("agent " + name + " references unknown provider: " + provider)
        if item.model != "":
            provider_cfg = dataclasses.replace(provider_cfg, model=item.model)
        mode = PermissionMode(first_non_empty(item.permission_mode, str(cfg.permission_mode)))
        if not valid_permission_mode(mode):
            raise ValueError("agent " + name + " has invalid permission mode: " + str(mode))
        profiles[name] = AgentProfile(
            name=name,
            provider=provider,
            model=provider_cfg.model,
            prompt=item.prompt.strip() + skill_prompt,
            permission_mode=mode,
            tools=tuple(item.tools),
        )
    return profiles


def initial_messages(cwd: str) -> tuple[list[Message], Bundle]:
    """The built-in prompt plus every instruction layer that applies to ``cwd``.

    The bundle is returned alongside so session metadata can record where the
    instructions came from. It lives here rather than in the session module
    because :func:`initial_messages_with_agent` is its only caller and the session
    module would otherwise need a mutual import.
    """
    bundle = load_instructions(cwd)
    content = SYSTEM_PROMPT
    if bundle.content != "":
        content += "\n\n" + bundle.content
    return [Message(role=ROLE_SYSTEM, content=content)], bundle


def initial_messages_with_agent(cwd: str, profile: AgentProfile) -> tuple[list[Message], Bundle]:
    """:func:`initial_messages` with the active profile's prompt appended.

    The message value is frozen, so a replacement is built rather than mutated in
    place.
    """
    messages, bundle = initial_messages(cwd)
    return with_agent_profile(messages, profile), bundle
