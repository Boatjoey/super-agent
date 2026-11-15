"""Shell syntax never buys a command a more permissive approval path.

``runtime/execution/command_analyzer.py`` classifies a ``bash`` or ``run_command``
command from its text, and the class picks the approval path (docs/spec/config.md,
权限: 命令分类用于决定审批路径). The text is read by a heuristic that may be wrong
(docs/spec/tools.md, 沙箱), but the user must stay in control of what the agent runs
(docs/design/constraints.md, 授权与工作范围), and a tool call is the model's proposal,
not an authorisation (docs/design/software-architecture.md, 操作授权). The heuristic
may therefore err only towards asking: a proposal must not choose a more permissive
path through the way it is written.

"More permissive" is measured on the approval path itself: the default policy's
decision for a ``bash`` call in every permission mode, with and without an allow rule
for the tool, and with network access denied or allowed. Running directly is the most
permissive decision and a denial the least. Rules that match command prefixes, paths
or environment names are left out: the specification does not say how they treat a
composed line.

Each case pins a line that once took a more permissive path than a command it runs.
"""

from __future__ import annotations

import functools
import json

import pytest

from super_agent.runtime.execution import (
    PERMISSION_MODE_ACCEPT_EDITS,
    PERMISSION_MODE_ASK,
    PERMISSION_MODE_BYPASS,
    PERMISSION_MODE_PLAN,
    DefaultPolicy,
    PermissionRules,
    ToolDecision,
    ToolPolicyInput,
    analyzeCommandRequest,
    new_policy,
)
from super_agent.runtime.permission.types import (
    COMMAND_CLASS_READ_ONLY,
    CommandClass,
    Request as PermissionRequest,
)
from super_agent.runtime.protocol.types import ToolCall, ToolSpec

# --- The approval path -------------------------------------------------------

_RULES: tuple[tuple[str, PermissionRules], ...] = (
    ("", PermissionRules()),
    (" +allow bash", PermissionRules(allow_tools=("bash",))),
    (" +network", PermissionRules(network="allow")),
    (" +allow bash +network", PermissionRules(allow_tools=("bash",), network="allow")),
)

_POLICIES: tuple[tuple[str, DefaultPolicy], ...] = tuple(
    (f"{mode}{label}", new_policy(mode, rules))
    for mode in (PERMISSION_MODE_ASK, PERMISSION_MODE_ACCEPT_EDITS, PERMISSION_MODE_PLAN, PERMISSION_MODE_BYPASS)
    for label, rules in _RULES
)

#: The ``bash`` tool is risky, so the policy sees it that way here too.
_BASH_SPECS = (ToolSpec(name="bash", risky=True),)

#: Larger is stricter: running directly asks nobody, approval asks the user, a denial never runs.
_STRICTNESS = {
    ToolDecision.DECISION_RUN_DIRECTLY: 0,
    ToolDecision.DECISION_NEEDS_APPROVAL: 1,
    ToolDecision.DECISION_DENIED: 2,
}


@functools.cache
def approval_path(command: str) -> tuple[ToolDecision, ...]:
    """Every policy's decision for ``command`` as a ``bash`` call."""
    call = ToolCall(id="call-1", name="bash", input=json.dumps({"command": command}))
    policy_input = ToolPolicyInput(tool_specs=_BASH_SPECS)
    return tuple(policy.classify_tool_call(call, policy_input) for _label, policy in _POLICIES)


def command_class(command: str) -> CommandClass:
    return analyzeCommandRequest(PermissionRequest(command=command)).command_class


def relaxation(command: str, baseline: str) -> str | None:
    """Where ``command`` takes a more permissive path than ``baseline``, or ``None``."""
    pairs = zip(_POLICIES, approval_path(command), approval_path(baseline), strict=True)
    for (label, _policy), got, floor in pairs:
        if _STRICTNESS[got] < _STRICTNESS[floor]:
            return (
                f"{command!r} ({command_class(command)}) is more permissive than {baseline!r} "
                f"({command_class(baseline)}) under {label}: {got.name} instead of {floor.name}"
            )
    return None


def assert_not_relaxed(command: str, baseline: str) -> None:
    found = relaxation(command, baseline)
    assert found is None, found


# --- Pinned counterexamples --------------------------------------------------


@pytest.mark.parametrize(
    ("command", "baseline"),
    [
        ("echo hi;rm -r build", "rm -r build"),
        ("echo hi&&rm -r build", "rm -r build"),
        ("echo hi||rm -r build", "rm -r build"),
        ("echo hi|rm -r build", "rm -r build"),
        ("echo hi&rm -r build", "rm -r build"),
        ("echo $(rm -r build)", "rm -r build"),
        ("echo `rm -r build`", "rm -r build"),
        ("r''m -r build", "rm -r build"),
        ("\\rm -r build", "rm -r build"),
        ('r"m" -r build', "rm -r build"),
        ("$'rm' -r build", "rm -r build"),
        ("r\\\nm -r build", "rm -r build"),
        ("X=rm; $X -r build", "rm -r build"),
        ('bash -c "echo hi;rm -r build"', "rm -r build"),
        ("ls;curl example.com/x.sh", "curl example.com/x.sh"),
        ("echo $(c''url example.com/x.sh)", "curl example.com/x.sh"),
        ("ls&&pip install requests", "pip install requests"),
        ("echo hi;touch build.txt", "touch build.txt"),
        ("\\touch build.txt", "touch build.txt"),
    ],
    ids=repr,
)
def test_command_glued_to_an_operator_or_respelled_keeps_its_class(command: str, baseline: str) -> None:
    """A command name touching ``;``, ``|``, ``&``, ``$(`` or a backtick, quoted in pieces,
    escaped, or bound to a variable is still that command."""
    assert_not_relaxed(command, baseline)


@pytest.mark.parametrize(
    ("command", "baseline"),
    [
        ("ls|tee out.txt", "ls | tee out.txt"),
        ("ls |& tee out.txt", "ls 2>&1 | tee out.txt"),
        ('ls | "tee" out.txt', "ls | tee out.txt"),
        ("git\tpush origin main", "git push origin main"),
        ('git "push" origin main', "git push origin main"),
        ("npm\tinstall left-pad", "npm install left-pad"),
    ],
    ids=repr,
)
def test_write_and_network_intent_survive_spacing_and_quoting(command: str, baseline: str) -> None:
    """``| tee`` and a package manager's install or push read the same however they are spaced or quoted."""
    assert_not_relaxed(command, baseline)


@pytest.mark.parametrize(
    ("command", "baseline"),
    [
        ("git status; touch pwned", "touch pwned"),
        ("git status && mv a.txt b.txt", "mv a.txt b.txt"),
        ("git status && git commit -m msg", "git commit -m msg"),
        ("git log > out.txt", "echo x > out.txt"),
        ("git log --oneline >> out.txt", "echo x > out.txt"),
        ("git diff | tee patch.diff", "ls | tee patch.diff"),
        ('git log "$(touch pwned)"', "touch pwned"),
        ('git diff HEAD | eval "git log --oneline > out.txt"', "echo x > out.txt"),
    ],
    ids=repr,
)
def test_read_only_git_exemption_does_not_cover_the_rest_of_the_line(command: str, baseline: str) -> None:
    """``git status`` is read-only; a write chained to it or redirected out of it is not."""
    assert_not_relaxed(command, baseline)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git log --oneline | head -20",
        "git status && git log",
        "git status 2>&1",
        'git log --grep="a; b | c"',
        "git log --format='%h (%an)'",
    ],
    ids=repr,
)
def test_read_only_git_exemption_still_covers_a_harmless_line(command: str) -> None:
    """The exemption stays for git reads piped into readers, descriptor copies, and quoted operators."""
    assert command_class(command) == COMMAND_CLASS_READ_ONLY
