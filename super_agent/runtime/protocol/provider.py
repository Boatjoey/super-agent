"""Application-owned provider configuration."""

import dataclasses

from super_agent.jsonutil import json_field


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderConfig:
    """How one provider is configured.

    Field names and JSON keys are fixed by the settings file.
    """

    base_url: str = dataclasses.field(default="", metadata=json_field(name="base_url"))
    api_key: str = dataclasses.field(default="", metadata=json_field(name="api_key"))
    model: str = dataclasses.field(default="", metadata=json_field(name="model"))
