"""Provider credential resolution and runtime configuration.

The change this pins: a provider with no usable key no longer fails startup.
The application starts with an empty credential so a front end can offer to
enter one, and the authentication error surfaces on the first turn instead of
blocking the interface before it appears.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from super_agent.app.config import Lookup, Settings, resolveProviderConfig


def lookup(values: Mapping[str, str] | None = None) -> Lookup:
    """A table lookup that reports "not set" as ``None``."""
    table = {} if values is None else dict(values)

    def get(key: str) -> str | None:
        return table.get(key)

    return get


def settings_with(provider: str, api_key: str) -> Settings:
    """A settings value naming one provider with the given key."""
    from super_agent.llm import ProviderConfig

    return Settings(provider=provider, providers={provider: ProviderConfig(api_key=api_key, model="m")})


def test_missing_credential_is_no_longer_a_startup_failure() -> None:
    """A named provider with no key resolves to an empty credential, not an error."""
    settings = settings_with("deepseek", "sk-...")

    resolved = resolveProviderConfig(settings, "deepseek", lookup())

    assert resolved.api_key == ""


def test_missing_credential_still_accepts_the_environment() -> None:
    """The environment variable still supplies the key when settings has none."""
    settings = settings_with("deepseek", "sk-...")

    resolved = resolveProviderConfig(settings, "deepseek", lookup({"DEEPSEEK_API_KEY": "from-env"}))

    assert resolved.api_key == "from-env"


def test_unknown_provider_is_still_a_failure() -> None:
    """A provider that is not configured at all remains a startup failure."""
    settings = settings_with("deepseek", "sk-...")

    with pytest.raises(ValueError):
        resolveProviderConfig(settings, "openai", lookup())


def test_placeholder_is_treated_as_unset() -> None:
    """The template placeholder ``sk-...`` never counts as a credential."""
    settings = settings_with("deepseek", "sk-...")

    resolved = resolveProviderConfig(settings, "deepseek", lookup())

    assert resolved.api_key == ""


def test_a_real_key_passes_through_unchanged() -> None:
    """A real key survives resolution untouched."""
    settings = settings_with("openai", "real-key")

    resolved = resolveProviderConfig(settings, "openai", lookup())

    assert resolved.api_key == "real-key"
