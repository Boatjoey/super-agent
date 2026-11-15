"""Workspace access policy and the session filesystem adapter.

:class:`Context` is the process-independent source of truth for roots and cwd;
:class:`Workspace` is the switchable binding the session and the built-in tools
share.
"""

from __future__ import annotations

from super_agent.workspace.context import (
    ACCESS_READ as ACCESS_READ,
    ACCESS_READ_WRITE as ACCESS_READ_WRITE,
    Access as Access,
    Context as Context,
    Root as Root,
    canonical_directory as canonical_directory,
    canonical_nearest as canonical_nearest,
    new_context as new_context,
    new_default_context as new_default_context,
)
from super_agent.workspace.workspace import (
    Workspace as Workspace,
    build_context as build_context,
    capture as capture,
    context_from_spec as context_from_spec,
    detect_content_type as detect_content_type,
    from_session_access as from_session_access,
    new as new,
    same_path as same_path,
    spec_from_context as spec_from_context,
    to_session_access as to_session_access,
)

__all__ = [
    "ACCESS_READ",
    "ACCESS_READ_WRITE",
    "Access",
    "Context",
    "Root",
    "Workspace",
    "build_context",
    "canonical_directory",
    "canonical_nearest",
    "capture",
    "context_from_spec",
    "detect_content_type",
    "from_session_access",
    "new",
    "new_context",
    "new_default_context",
    "same_path",
    "spec_from_context",
    "to_session_access",
]
