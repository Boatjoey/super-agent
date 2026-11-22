"""Strict sandbox construction on platforms that have no implementation.

The refusal is deliberate: strict is the default mode, and silently running
commands with the user's full authority would turn a missing isolation mechanism
into an unnoticed privilege change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from super_agent.tools.sandbox import CommandSandbox, SandboxConfig


def new_platform_sandbox(config: SandboxConfig) -> CommandSandbox:
    """Refuse to construct a sandbox this platform cannot provide."""
    raise RuntimeError(
        "strict sandbox is currently supported only on Linux and macOS; set sandbox.mode to off explicitly"
    )
