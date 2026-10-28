"""Workflow prompts shared by both front ends.

The terminal exposes these as slash commands and the Web as workflow buttons; the
prompt text lives here so the two cannot drift. They are application content, not
display values: changing one changes what both front ends ask the model to do.
"""

from __future__ import annotations

from typing import Final

__all__ = ["WORKFLOW_PROMPTS"]

#: The named prompts a front end may start a turn with, by stable name.
WORKFLOW_PROMPTS: Final[dict[str, str]] = {
    "review": (
        "Review the current changes. Inspect the git diff, relevant code, and LSP diagnostics when configured, "
        "then report only actionable defects with file and line references. Do not modify files."
    ),
    "fix-ci": (
        "Inspect the repository CI configuration and current failures, reproduce them locally, implement the "
        "fixes, and verify the result."
    ),
    "commit-message": (
        "Inspect the current git diff and suggest one concise conventional commit subject. "
        "Do not modify files or commit."
    ),
}
