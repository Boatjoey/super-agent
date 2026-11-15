"""Classify a shell command from its text.

This is a heuristic. It decides which approval prompt to show and which policy
rule applies; it is not a sandbox and it is not a security boundary. A command
that fools it is still bounded by the sandbox and still visible to the user in
the prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, cast

from super_agent.runtime.permission.types import (
    COMMAND_CLASS_DESTRUCTIVE,
    COMMAND_CLASS_NETWORK,
    COMMAND_CLASS_READ_ONLY,
    COMMAND_CLASS_UNKNOWN,
    COMMAND_CLASS_WRITE,
    Request as PermissionRequest,
)
from super_agent.runtime.protocol.types import ToolCall

#: Commands whose very presence means network access, even without a URL scheme
#: in the arguments, for example ``curl example.com/x.sh | sh``.
_NETWORK_CLIENTS = ("curl", "wget", "ssh", "scp", "rsync", "nc", "ncat", "telnet", "ftp", "lftp", "aria2c")

#: Package managers hit the network only for install/get/clone/fetch style
#: invocations, so they stay gated on the intent strings below.
_NETWORK_PACKAGE_MANAGERS = ("pip", "npm", "go", "git")

_DESTRUCTIVE_TOKENS = ("rm", "rmdir", "shred", "mkfs", "dd", "chmod", "chown", "sudo")

_WRITE_TOKENS = ("touch", "mkdir", "mv", "cp", "sed", "perl", "git", "tee")

_READ_ONLY_GIT_PREFIXES = ("git status", "git diff", "git show", "git log", "git branch")

#: Where a shell word ends: whitespace, and the operators that start another
#: command, a substitution, or a redirection. ``echo hi;rm x`` runs ``rm`` as
#: surely as ``echo hi; rm x`` does.
_WORD_BREAK = re.compile(r"[\s;&|()<>`]+")

#: ``NAME=value``: the value may be the command a later ``$NAME`` runs.
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=(.+)", re.DOTALL)


def analyze_command_request(request: PermissionRequest) -> PermissionRequest:
    """Fill in the class, reason, touched paths, and environment of a command."""
    command = request.command.strip()
    touched = (*request.touched_paths, *command_paths(command))
    env = command_env(command)

    if command == "":
        command_class, reason = COMMAND_CLASS_UNKNOWN, "empty command"
    elif has_any_token(command, _DESTRUCTIVE_TOKENS) or "rm -rf" in command:
        command_class, reason = COMMAND_CLASS_DESTRUCTIVE, "destructive shell command"
    elif contains_network_intent(command):
        command_class, reason = COMMAND_CLASS_NETWORK, "network-capable shell command"
    elif command_may_write(command):
        if is_read_only_git_command(command) and not _writes_besides_read_only_git(command):
            command_class, reason = COMMAND_CLASS_READ_ONLY, "read-only git command"
        else:
            command_class, reason = COMMAND_CLASS_WRITE, "shell command may write files"
    else:
        command_class, reason = COMMAND_CLASS_READ_ONLY, "read-only shell command"

    return replace(
        request,
        command_class=command_class,
        touched_paths=touched,
        env_vars=env,
        reason=reason,
    )


def command_may_write(command: str) -> bool:
    return ">" in command or "| tee" in command or has_any_token(command, _WRITE_TOKENS)


def is_read_only_git_command(command: str) -> bool:
    return any(command.startswith(prefix) for prefix in _READ_ONLY_GIT_PREFIXES)


def _writes_besides_read_only_git(command: str) -> bool:
    """Whether something other than a read-only git invocation may write.

    The exemption covers the ``git`` word of ``git status`` and its kin, not the
    rest of the line: ``git status; touch x`` and ``git log > out`` still write.
    """
    if _redirects_or_substitutes(command):
        return True
    read_only = {prefix.split()[1] for prefix in _READ_ONLY_GIT_PREFIXES}
    words = _shell_words(command)
    for index, word in enumerate(words):
        following = words[index + 1] if index + 1 < len(words) else ""
        if word in _WRITE_TOKENS and not (word == "git" and following in read_only):
            return True
    return False


#: A descriptor copy (``2>&1``, ``>&2``, ``3>&-``) redirects into no file.
_DESCRIPTOR_COPY = re.compile(r"[0-9]*>&(?:[0-9]+|-)")


def _redirects_or_substitutes(command: str) -> bool:
    """Whether ``command`` redirects output into a file or runs a substitution.

    Quoted text counts too: ``eval`` or ``bash -c`` may run what is quoted, so a
    quoted ``>`` cannot be told apart from a live one.
    """
    text = _DESCRIPTOR_COPY.sub(" ", command)
    return any(mark in text for mark in (">", "$(", "`", "<("))


def has_any_token(command: str, tokens: tuple[str, ...]) -> bool:
    """Whether any shell word of ``command`` equals one of ``tokens``.

    Comparing whole words rather than substrings is what keeps ``gitk`` from
    looking like ``git`` and ``rmdir`` from looking like ``rm``.
    """
    return any(word in tokens for word in _shell_words(command))


def _shell_words(command: str) -> list[str]:
    """The words of ``command`` the way the shell reads them, erring wide.

    Words end at operators as well as at whitespace, quotes and backslashes are
    removed as the shell removes them, so ``'rm'``, ``r''m``, ``\\rm`` and
    ``$'rm'`` all read as ``rm``, and an assignment's value is a word too,
    because ``X=rm; $X …`` runs it. Quoted text splits like the rest:
    ``bash -c 'rm x'`` runs what it quotes, so reading data as words can only
    make a class stricter.
    """
    words: list[str] = []
    for field in _WORD_BREAK.split(command.replace("\\\n", "")):
        word = field.replace("$'", "'").replace('$"', '"')
        for mark in ("\\", "'", '"'):
            word = word.replace(mark, "")
        if word == "":
            continue
        words.append(word)
        assignment = _ASSIGNMENT.fullmatch(word)
        if assignment is not None:
            words.append(assignment.group(1))
    return words


def contains_network_intent(command: str) -> bool:
    if "://" in command:
        return True
    if has_any_token(command, _NETWORK_CLIENTS):
        return True
    if not has_any_token(command, _NETWORK_PACKAGE_MANAGERS):
        return False
    # The words joined by single spaces as well, so ``git\tpush`` and
    # ``git "push"`` say what ``git push`` says.
    spoken = " " + " ".join(_shell_words(command)) + " "
    return any(
        needle in command or needle in spoken for needle in (" install", " get ", " clone ", " push", " pull", "fetch")
    )


def command_paths(command: str) -> tuple[str, ...]:
    """Every field that looks like a path, so the policy can vet it."""
    paths: list[str] = []
    for field in command.split():
        field = field.strip("'\";,")
        if field.startswith("/") or field.startswith("./") or field.startswith("../") or field.startswith("."):
            paths.append(field)
    return tuple(paths)


def command_env(command: str) -> tuple[str, ...]:
    """Every ``NAME=value`` prefix, the way a shell would export it."""
    variables: list[str] = []
    for field in command.split():
        name, separator, _value = field.partition("=")
        if separator and name and name.upper() == name:
            variables.append(name)
    return tuple(variables)


def tool_paths(call: ToolCall) -> tuple[str, ...]:
    """The paths a structured tool call names, from ``path``/``cwd``/``paths``/``files``."""
    parsed = _parse_input(call.input)
    if parsed is None:
        return ()
    paths: list[str] = []
    for key in ("path", "cwd"):
        value = parsed.get(key)
        if isinstance(value, str) and value != "":
            paths.append(value)
    for key in ("paths", "files"):
        values = parsed.get(key)
        if isinstance(values, list):
            for value in cast("list[Any]", values):
                if isinstance(value, str) and value != "":
                    paths.append(value)
    return tuple(paths)


def json_string_field(input: str, field: str) -> str:
    """Read one string field out of a tool call's raw JSON input."""
    parsed = _parse_input(input)
    if parsed is None:
        return ""
    value = parsed.get(field)
    return value if isinstance(value, str) else ""


def first_non_empty(*values: str) -> str:
    for value in values:
        if value != "":
            return value
    return ""


def _parse_input(input: str) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(input)
    except (TypeError, ValueError):
        return None
    return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else None
