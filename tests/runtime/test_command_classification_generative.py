"""Shell syntax never buys a command a more permissive approval path.

``runtime/execution/command_analyzer.py`` classifies a ``bash`` or ``run_command``
command from its text, and the class picks the approval path (docs/spec/config.md,
权限: 命令分类用于决定审批路径). The text is read by a heuristic that may be wrong
(docs/spec/tools.md, 沙箱), but the user must stay in control of what the agent runs
(docs/design/constraints.md, 授权与工作范围), and a tool call is the model's proposal,
not an authorisation (docs/design/software-architecture.md, 操作授权). The heuristic
may therefore err only towards asking: a proposal must not choose a more permissive
path through the way it is written. The invariants checked here:

1. Spelling. Quoting or escaping a word (``'rm'``, ``r''m``, ``\\rm``, ``$'rm'``), the
   whitespace around an operator, or a line continuation does not change what runs,
   so it does not relax the path.
2. Composition. A line that runs a command after ``;``, ``&&``, ``||``, ``|``, ``|&``,
   ``&`` or a newline, inside ``( … )``, ``{ …; }``, ``$( … )``, backticks,
   ``bash -c``, ``eval``, a here-document fed to ``bash``, a control structure or a
   function, or behind ``env``, ``nice``, ``nohup``, ``command`` or ``time``, is at
   least as strict as that command alone.
3. Redirection. A redirection does not relax the path, and a line that redirects
   output into a file is at least as strict as ``echo x > out.txt``.
4. Variables. Assignment prefixes and ``$VAR``/``${VAR}`` arguments do not relax the
   path, and a command name bound to a variable on the same line (``X=rm; $X -rf
   build``) counts as that command.
5. Quoted operators are data. ``;``, ``|``, ``&`` or a parenthesis inside quotes
   composes nothing, so quoting one into the argument of a read-only git command keeps
   the command read-only. A quoted redirection or substitution is read as live, since
   ``eval`` or ``bash -c`` may run the quoted text.

"More permissive" is measured on the approval path itself: the default policy's
decision for a ``bash`` call in every permission mode, with and without an allow rule
for the tool, and with network access denied or allowed. Running directly is the most
permissive decision and a denial the least. Rules that match command prefixes, paths
or environment names are left out: the specification does not say how they treat a
composed line.

Only the safe direction is asserted. The analyzer reads quoted text as if it were code
(``bash -c 'rm -rf build'`` runs what it quotes), so data that merely mentions a risky
word may be classified more strictly than it needs to be; nothing here forbids that.

The generator is a seeded grammar, deterministic for a given seed:
``SUPER_AGENT_SHELL_SEED`` picks the seed and ``SUPER_AGENT_SHELL_CASES`` the number of
lines per property. Every failure names the case seed that regenerates its line through
:func:`generate_line`, ``generate_line(Draw("<seed>/<index>"))``.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import os
import random
from collections.abc import Callable

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
    analyze_command_request,
    new_policy,
)
from super_agent.runtime.permission.types import (
    COMMAND_CLASS_DESTRUCTIVE,
    COMMAND_CLASS_NETWORK,
    COMMAND_CLASS_READ_ONLY,
    COMMAND_CLASS_WRITE,
    CommandClass,
    Request as PermissionRequest,
)
from super_agent.runtime.protocol.types import ToolCall, ToolSpec

SEED = int(os.environ.get("SUPER_AGENT_SHELL_SEED", "20261115"))
CASES = int(os.environ.get("SUPER_AGENT_SHELL_CASES", "1500"))

#: How many failing lines one property reports before it stops looking.
MAX_REPORTED = 5

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
    return analyze_command_request(PermissionRequest(command=command)).command_class


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


# --- The grammar -------------------------------------------------------------

#: The simple commands the generator wraps, spelled plainly. Their own classes span
#: read-only, write, network and destructive, which
#: :func:`test_generator_wraps_read_only_and_risky_commands` checks, so every property
#: exercises risky commands as well as harmless ones. None names a path the policy
#: refuses outright, and none is a shell builtin.
SIMPLE_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("ls", "-la"),
    ("cat", "README.md"),
    ("grep", "-n", "TODO", "notes.txt"),
    ("wc", "-l", "notes.txt"),
    ("head", "-n", "5", "notes.txt"),
    ("git", "status", "--short"),
    ("git", "log", "--oneline"),
    ("git", "diff", "HEAD"),
    ("touch", "build.txt"),
    ("mkdir", "-p", "out"),
    ("mv", "a.txt", "b.txt"),
    ("cp", "a.txt", "b.txt"),
    ("sed", "-i", "s/a/b/", "notes.txt"),
    ("git", "commit", "-m", "msg"),
    ("curl", "https://example.com"),
    ("curl", "example.com/x.sh"),
    ("wget", "example.com/file"),
    ("ssh", "host", "uptime"),
    ("pip", "install", "requests"),
    ("npm", "install", "left-pad"),
    ("git", "push", "origin", "main"),
    ("go", "get", "example.com/x"),
    ("rm", "-rf", "build"),
    ("rm", "notes.txt"),
    ("rmdir", "empty"),
    ("chmod", "+x", "run.sh"),
    ("sudo", "ls"),
    ("dd", "if=a.img", "of=b.img"),
    ("shred", "notes.txt"),
)

#: The canonical file write a redirecting line is measured against.
REDIRECT_WRITE = "echo x > out.txt"

#: Output redirections that create or overwrite a file. ``&>>``, like ``|&``, needs bash 4.
FILE_REDIRECTS = ("> out.txt", ">> out.txt", "2> err.txt", ">| out.txt", "&> out.txt", "&>> out.txt", ">out.txt")

#: Redirections that write no file: input, a here-string, and descriptor copies.
OTHER_REDIRECTS = ("< in.txt", "0<in.txt", "<<< word", "2>&1", ">&2", "1>&2")

OPERATORS = (";", "&&", "||", "|", "|&", "&", "\n")


class Draw(random.Random):
    """The seeded source of one line, which also fixes how oddly the line is written.

    Half the lines are written plainly, as most real commands are, and the rest respell
    a quarter or three quarters of their words and gaps. Plain lines are what
    prefix-based rules see; respelled ones are what the spelling invariant is about.
    """

    def __init__(self, seed: str) -> None:
        super().__init__(seed)
        self.oddity: float = self.choice((0.0, 0.0, 0.25, 0.75))

    def odd(self) -> bool:
        return self.random() < self.oddity


@dataclasses.dataclass(frozen=True, slots=True)
class Line:
    """A generated command line and what it must be at least as strict as.

    ``runs`` holds the plain spelling of every simple command the line executes, and
    ``writes`` says whether it redirects output into a file.
    """

    text: str
    runs: tuple[str, ...]
    writes: bool = False


def spell(draw: Draw, word: str) -> str:
    """``word`` written so that the shell still reads ``word``."""
    if not draw.odd():
        return word
    choices = [f"'{word}'", f'"{word}"', f"$'{word}'", "\\" + word]
    if len(word) > 1:
        cut = draw.randrange(1, len(word))
        head, tail = word[:cut], word[cut:]
        choices += [
            head + "''" + tail,
            head + '""' + tail,
            head + '"' + tail + '"',
            head + "\\" + tail,
            head + "\\\n" + tail,
        ]
    return draw.choice(choices)


def gap(draw: Draw) -> str:
    """Whitespace between two words; neither its kind nor its width changes the words."""
    return draw.choice(("  ", "\t", " \t ")) if draw.odd() else " "


def pad(draw: Draw) -> str:
    """Whitespace beside an operator, which the operator does not need."""
    return draw.choice(("", "  ", "\t")) if draw.odd() else " "


def render(draw: Draw, words: tuple[str, ...]) -> str:
    return "".join((gap(draw) if index else "") + spell(draw, word) for index, word in enumerate(words))


def plain(words: tuple[str, ...]) -> str:
    return " ".join(words)


def shell_quote(draw: Draw, text: str) -> str:
    """``text`` as one quoted shell word, in single or in double quotes."""
    if draw.random() < 0.5:
        return "'" + text.replace("'", "'\\''") + "'"
    return '"' + "".join("\\" + char if char in '\\"$`' else char for char in text) + '"'


# A simple command, optionally behind a wrapper, an assignment, a variable, or a
# leading redirection. These forms need a simple command, not a compound one.


def bare(draw: Draw, words: tuple[str, ...]) -> Line:
    return Line(render(draw, words), (plain(words),))


def wrapped(draw: Draw, words: tuple[str, ...]) -> Line:
    wrapper = draw.choice(("env", "nice", "nohup", "command", "time", "env FOO=1"))
    return Line(wrapper + gap(draw) + render(draw, words), (plain(words),))


def assigned(draw: Draw, words: tuple[str, ...]) -> Line:
    prefix = draw.choice(("FOO=bar", 'FOO="a b"', "FOO=1 BAR=$HOME", "PAGER=${PAGER:-cat}"))
    return Line(prefix + gap(draw) + render(draw, words), (plain(words),))


def indirect(draw: Draw, words: tuple[str, ...]) -> Line:
    """The command name comes from a variable set earlier on the same line."""
    name, rest = words[0], words[1:]
    variable = draw.choice(("X", "cmd", "TOOL"))
    use = draw.choice((f"${variable}", f"${{{variable}}}", f'"${variable}"', f'"${{{variable}}}"'))
    if rest and draw.random() < 0.3:
        # Two words in one unquoted variable split back into two words.
        assignment, use, rest = f'{variable}="{name} {rest[0]}"', f"${variable}", rest[1:]
    else:
        assignment = draw.choice(("", "export ")) + f"{variable}={spell(draw, name)}"
    separator = draw.choice((";", "; ", " && ", "\n"))
    tail = (gap(draw) + render(draw, rest)) if rest else ""
    return Line(assignment + separator + use + tail, (plain(words),))


def redirected_first(draw: Draw, words: tuple[str, ...]) -> Line:
    return Line(draw.choice(FILE_REDIRECTS) + gap(draw) + render(draw, words), (plain(words),), writes=True)


SIMPLE_FORMS: tuple[Callable[[Draw, tuple[str, ...]], Line], ...] = (
    bare,
    bare,
    bare,
    wrapped,
    assigned,
    indirect,
    redirected_first,
)


def simple_line(draw: Draw) -> Line:
    return draw.choice(SIMPLE_FORMS)(draw, draw.choice(SIMPLE_COMMANDS))


# Compound forms: each runs every line it is built from.


def chained(draw: Draw, depth: int) -> Line:
    left, right = generate(draw, depth), generate(draw, depth)
    operator = draw.choice(OPERATORS)
    # A right side opening with a redirection keeps its distance, or ``;`` and ``&>``
    # would fuse into the ``;&`` case terminator.
    after = " " if right.text[:1] in ("<", ">", "&") else pad(draw)
    joint = "\n" if operator == "\n" else pad(draw) + operator + after
    return Line(left.text + joint + right.text, left.runs + right.runs, left.writes or right.writes)


def subshell(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    # ``((`` would open an arithmetic command instead of two subshells.
    opening = "( " if inner.text.startswith("(") or draw.odd() else "("
    return Line(opening + inner.text + ")", inner.runs, inner.writes)


def grouped(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    text = draw.choice(("{ " + inner.text + "; }", "{\n" + inner.text + "\n}"))
    return Line(text, inner.runs, inner.writes)


def substituted(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    opening = "$( " if inner.text.startswith("(") else "$("
    substitution = opening + inner.text + ")"
    if draw.random() < 0.5:
        form = draw.choice(("echo {}", 'echo "{}"', "{}", "v={}", "test -n {}", 'test -n "{}"'))
    else:
        form = draw.choice(("echo {}", "{}", "v={}"))
        if "`" not in inner.text and "\\" not in inner.text:
            substitution = "`" + inner.text + "`"
    return Line(form.replace("{}", substitution), inner.runs, inner.writes)


def shell_string(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    runner = draw.choice(("bash" + gap(draw) + "-c", "eval"))
    return Line(runner + gap(draw) + shell_quote(draw, inner.text), inner.runs, inner.writes)


#: Control structures, each running ``{}`` at least once. The function is defined and
#: called inside one group so that a pipe in front of it cannot strand the call.
CONTROL_FORMS = (
    "if true; then {}; fi",
    "if {}; then :; fi",
    "for i in 1; do {}; done",
    "while {}; do break; done",
    "case x in (x) {};; esac",
    "{ f() { {}; }; f; }",
)


def controlled(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    return Line(draw.choice(CONTROL_FORMS).replace("{}", inner.text), inner.runs, inner.writes)


def redirected(draw: Draw, depth: int) -> Line:
    inner = generate(draw, depth)
    if draw.random() < 0.6:
        return Line(inner.text + " " + draw.choice(FILE_REDIRECTS), inner.runs, writes=True)
    return Line(inner.text + " " + draw.choice(OTHER_REDIRECTS), inner.runs, inner.writes)


COMPOUND_FORMS: tuple[Callable[[Draw, int], Line], ...] = (
    chained,
    chained,
    chained,
    subshell,
    grouped,
    substituted,
    shell_string,
    controlled,
    redirected,
    redirected,
)


def generate(draw: Draw, depth: int) -> Line:
    if depth <= 0 or draw.random() < 0.25:
        return simple_line(draw)
    return draw.choice(COMPOUND_FORMS)(draw, depth - 1)


def generate_line(draw: Draw) -> Line:
    """One whole line, sometimes negated or carried by a here-document."""
    line = generate(draw, 3)
    roll = draw.random()
    if roll < 0.08:
        return Line("! " + line.text, line.runs, line.writes)
    if roll < 0.16:
        delimiter = draw.choice(("'EOF'", '"EOF"'))
        return Line("bash <<" + delimiter + "\n" + line.text + "\nEOF", line.runs, line.writes)
    if roll < 0.24:
        return Line(line.text + " <<'EOF'\nsome input\nEOF", line.runs, line.writes)
    return Line(("\t " if draw.odd() else "") + line.text, line.runs, line.writes)


def read_only_git_with_quoted_operators(draw: Draw) -> str:
    """A read-only git command whose one quoted argument holds operators and harmless letters.

    The letters cannot spell a command the analyzer knows, so only the operators could
    change the class, and inside quotes they are data. Redirections and substitutions
    are left out on purpose; see invariant 5.
    """
    command = draw.choice(
        ("git status --short --", "git log --oneline --grep=", "git diff HEAD --", "git show --format=")
    )
    data = "".join(draw.choice("xyzqk019 ;|&()%-") for _ in range(draw.randint(1, 16)))
    quoted = draw.choice((f"'{data}'", f'"{data}"'))
    joint = "" if command.endswith("=") else " "
    return command + joint + quoted


# --- Properties --------------------------------------------------------------


def test_generator_wraps_read_only_and_risky_commands() -> None:
    classes = {command_class(plain(words)) for words in SIMPLE_COMMANDS}

    assert classes >= {COMMAND_CLASS_READ_ONLY, COMMAND_CLASS_WRITE, COMMAND_CLASS_NETWORK, COMMAND_CLASS_DESTRUCTIVE}


def test_generated_lines_are_reproducible_from_their_case_seed() -> None:
    assert generate_line(Draw(f"{SEED}/7")) == generate_line(Draw(f"{SEED}/7"))


def _report(failures: list[str], seed: int) -> str:
    replay = f"replay with SUPER_AGENT_SHELL_SEED={seed} uv run pytest {__file__}"
    return "\n".join([*failures, replay])


@pytest.mark.parametrize("seed", [SEED], ids=lambda seed: f"seed={seed}")
def test_spelling_and_composition_never_relax_a_command(seed: int) -> None:
    failures: list[str] = []
    for index in range(CASES):
        case_seed = f"{seed}/{index}"
        line = generate_line(Draw(case_seed))
        floors = [*line.runs, REDIRECT_WRITE] if line.writes else list(line.runs)
        for floor in floors:
            found = relaxation(line.text, floor)
            if found is not None:
                failures.append(f"case {case_seed}: {found}")
                break
        if len(failures) >= MAX_REPORTED:
            break

    assert not failures, _report(failures, seed)


@pytest.mark.parametrize("seed", [SEED], ids=lambda seed: f"seed={seed}")
def test_quoted_operators_keep_a_read_only_git_command_read_only(seed: int) -> None:
    failures: list[str] = []
    for index in range(CASES):
        case_seed = f"{seed}/{index}"
        command = read_only_git_with_quoted_operators(Draw(case_seed))
        got = command_class(command)
        if got != COMMAND_CLASS_READ_ONLY:
            failures.append(f"case {case_seed}: {command!r} is {got}, not {COMMAND_CLASS_READ_ONLY}")
        if len(failures) >= MAX_REPORTED:
            break

    assert not failures, _report(failures, seed)
