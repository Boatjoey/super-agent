"""Scheduled-action execution and the permission policy.

``runtime/execution`` implements the outbound ports the engine drives: calling a
model, running a tool, deciding whether a call needs approval, and classifying a
command. A package spans several modules here, so this module stands in for the
package namespace.
"""

from __future__ import annotations

from super_agent.runtime.execution.action_queue import ActionQueue as ActionQueue
from super_agent.runtime.execution.action_result_resolver import (
    ActionResultInput as ActionResultInput,
    ActionResultResolver as ActionResultResolver,
    DefaultActionResultResolver as DefaultActionResultResolver,
)
from super_agent.runtime.execution.approval_store import (
    ApprovalKey as ApprovalKey,
    ApprovalStore as ApprovalStore,
    MemoryApprovalStore as MemoryApprovalStore,
    hash_canonical_input as hash_canonical_input,
    new_approval_key as new_approval_key,
)
from super_agent.runtime.execution.command_analyzer import (
    analyze_command_request as analyze_command_request,
    command_env as command_env,
    command_may_write as command_may_write,
    command_paths as command_paths,
    contains_network_intent as contains_network_intent,
    first_non_empty as first_non_empty,
    has_any_token as has_any_token,
    is_read_only_git_command as is_read_only_git_command,
    json_string_field as json_string_field,
    tool_paths as tool_paths,
)
from super_agent.runtime.execution.policy import (
    PERMISSION_MODE_ACCEPT_EDITS as PERMISSION_MODE_ACCEPT_EDITS,
    PERMISSION_MODE_ASK as PERMISSION_MODE_ASK,
    PERMISSION_MODE_BYPASS as PERMISSION_MODE_BYPASS,
    PERMISSION_MODE_PLAN as PERMISSION_MODE_PLAN,
    ZERO_PERMISSION_MODE as ZERO_PERMISSION_MODE,
    DefaultPolicy as DefaultPolicy,
    PermissionMode as PermissionMode,
    PermissionRules as PermissionRules,
    Policy as Policy,
    ToolDecision as ToolDecision,
    ToolPolicyInput as ToolPolicyInput,
    is_risky_tool as is_risky_tool,
    new_default_policy as new_default_policy,
    new_policy as new_policy,
    valid_permission_mode as valid_permission_mode,
)
from super_agent.runtime.execution.run_controller import (
    ActionID as ActionID,
    DefaultRunController as DefaultRunController,
    RunController as RunController,
    RunID as RunID,
)
from super_agent.runtime.execution.scheduled_action_executor import (
    ERR_APPROVAL_DISMISSED as ERR_APPROVAL_DISMISSED,
    ApprovalDismissed as ApprovalDismissed,
    ApprovalWaiter as ApprovalWaiter,
    DefaultScheduledActionExecutor as DefaultScheduledActionExecutor,
    ScheduledActionExecutor as ScheduledActionExecutor,
    ScheduledActionInput as ScheduledActionInput,
)
from super_agent.runtime.execution.scheduled_action_result import (
    ALL_SCHEDULED_ACTION_RESULTS as ALL_SCHEDULED_ACTION_RESULTS,
    ApprovalReceived as ApprovalReceived,
    ModelReplied as ModelReplied,
    PermissionChecked as PermissionChecked,
    ScheduledActionResult as ScheduledActionResult,
    ToolFinished as ToolFinished,
)
from super_agent.runtime.execution.scheduled_action_runner import (
    ActionCompletion as ActionCompletion,
    DefaultScheduledActionRunner as DefaultScheduledActionRunner,
    QueuedAction as QueuedAction,
    ScheduledActionRunner as ScheduledActionRunner,
)
