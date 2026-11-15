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
    hashCanonicalInput as hashCanonicalInput,
    new_approval_key as new_approval_key,
)
from super_agent.runtime.execution.command_analyzer import (
    analyzeCommandRequest as analyzeCommandRequest,
    commandEnv as commandEnv,
    commandMayWrite as commandMayWrite,
    commandPaths as commandPaths,
    containsNetworkIntent as containsNetworkIntent,
    firstNonEmpty as firstNonEmpty,
    hasAnyToken as hasAnyToken,
    isReadOnlyGitCommand as isReadOnlyGitCommand,
    jsonStringField as jsonStringField,
    toolPaths as toolPaths,
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
    isRiskyTool as isRiskyTool,
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
