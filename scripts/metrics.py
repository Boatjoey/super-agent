#!/usr/bin/env python3
"""Code metrics for the optimisation baseline.

The refactoring that follows G25 (PEP 8 names, the compatibility facade, mixins,
``Any`` and oversized files) needs numbers a machine can recompute and compare.
Every count here comes from the abstract syntax tree rather than from text
matching: a docstring that mentions ``Any`` or a test string that spells an import
is not code and is not counted.

    uv run python scripts/metrics.py                        # static metrics, Markdown on stdout
    uv run python scripts/metrics.py --json metrics.json    # the same metrics as JSON

The slow measurements are opt-in. ``--collect-tests`` runs pytest's collection,
``--coverage-file`` aggregates the data an earlier ``./scripts/coverage.sh`` left
behind, so CI does not run the suite a second time, and ``--cold-start-runs``
times fresh interpreter processes. The definitions travel with the output.

Values are reported, never judged. The exit status is non-zero only when the
inputs are not shaped the way the metrics assume (no Python files, a module that
does not parse, a missing or stale coverage file, an unrecognised pytest summary),
because reporting zeros there would record a false baseline.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime
import importlib.metadata
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Bumped whenever a key of the JSON output changes meaning or disappears.
SCHEMA_VERSION: Final[int] = 1

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The two measured trees, relative to the repository root.
PRODUCTION: Final[str] = "super_agent"
TESTS: Final[str] = "tests"

#: The root runtime package is a compatibility facade assembled from ``api_*.py``.
FACADE: Final[str] = "super_agent.runtime"
FACADE_PART_PREFIX: Final[str] = "super_agent.runtime.api_"

#: Modules that only re-export names owned elsewhere (G27). A module that has been
#: deleted is reported as removed, which is the intended end state, not an error.
COMPAT_MODULES: Final[tuple[str, ...]] = (
    "super_agent.app.agent_application",
    "super_agent.app.tui_adapter",
    "super_agent.app.workflows",
    "super_agent.runtime.machine.aliases",
    "super_agent.runtime.execution.aliases",
    "super_agent.runtime.session.aliases",
)

DEFAULT_TOP_FILES: Final[int] = 10

NAMING_CATEGORIES: Final[tuple[str, ...]] = (
    "functions",
    "classes",
    "parameters",
    "local_variables",
    "instance_attributes",
    "class_attributes",
    "module_names",
    "import_aliases",
)

#: One definition per metric. They are written into both outputs so a number is
#: never separated from what it counts.
DEFINITIONS: Final[dict[str, str]] = {
    "camel_case": (
        "A name is camelCase when, after any leading underscores, it starts with a lowercase letter and contains "
        "an uppercase letter (fooBar, _fooBar). Counts are per identifier: once per name in its scope."
    ),
    "functions": (
        "Function and method definitions whose name contains an uppercase letter; PEP 8 wants snake_case. "
        "A method decorated with @override is exempt, because its base class owns the name."
    ),
    "classes": "Class names that are not CapWords: after leading underscores they start lowercase or contain an underscore.",
    "parameters": "camelCase parameters of functions, methods and lambdas.",
    "local_variables": (
        "camelCase names bound inside a function by assignment, loop, with, except, walrus, comprehension or match "
        "targets, once per function; parameters and global or nonlocal names are excluded."
    ),
    "instance_attributes": (
        "camelCase attributes assigned through self (self.fooBar = ...), once per class, excluding names the class "
        "body declares, which count as class_attributes. pep8-naming has no rule for these."
    ),
    "class_attributes": "camelCase names bound in a class body, such as dataclass fields, once per class.",
    "module_names": "camelCase names bound at module scope by assignment-like statements, once per module.",
    "import_aliases": "camelCase names an import binds under a new name (import x as fooBar); x as x re-exports are not aliases.",
    "facade_imports": (
        "Import statements that bind the root super_agent.runtime facade or a name it re-exports, or that import "
        "one of its api_*.py parts. The facade's own __init__.py and api_*.py are excluded. Each statement counts "
        "once, wherever it stands, TYPE_CHECKING blocks included."
    ),
    "subpackage_imports_via_facade": (
        "from super_agent.runtime import <subpackage> statements. They import the owning subpackage and keep "
        "working once the facade is gone, so they are not facade imports."
    ),
    "compat_modules": (
        "Import statements that load one of the compatibility re-export modules, counted per module. Lines are "
        "physical lines of the module."
    ),
    "any": (
        "References to typing.Any in code, string type expressions in annotations, cast() and type aliases "
        "included; the import statement itself, comments and docstrings are not references."
    ),
    "mixins": "Classes whose name ends in Mixin, and classes that list such a class among their bases.",
    "largest_files": "Production files with the most physical lines (newline count, as wc -l reports it).",
    "tests_collected": (
        "Test items listed by pytest --collect-only -q: each parametrised case counts, and tests skipped on this "
        "platform are still collected."
    ),
    "coverage": (
        "Line coverage read from an existing coverage data file: covered statements over statements, per "
        "super_agent/<package> and per super_agent/runtime/<subpackage>. super_agent/runtime holds the facade's own "
        "files and super_agent the top-level modules."
    ),
    "cold_start": (
        "Wall-clock time of fresh `python -c <code>` processes started from the repository root: one unrecorded "
        "warm-up per probe first (it compiles bytecode and warms the OS file cache), then the probes interleaved; "
        "the median is the figure to compare. entry_import imports the console-script module super_agent.__main__, "
        "which is everything loaded before flag parsing, without configuration or a front end. terminal_import adds "
        "super_agent.tui, the default front end on Linux and macOS. interpreter runs `pass`, the floor on this machine."
    ),
}


class MetricsError(Exception):
    """The inputs are not shaped the way the metrics assume."""


# --- sources -----------------------------------------------------------------


@dataclass(frozen=True)
class SourceFile:
    """One parsed Python file of a measured tree."""

    #: POSIX path from the repository root, such as ``super_agent/app/config.py``.
    relative: str
    #: Dotted module name; a package's ``__init__.py`` is the package itself.
    module: str
    is_package: bool
    tree: ast.Module
    lines: int

    @property
    def package(self) -> str:
        """The ``__package__`` that relative imports in this file resolve against."""
        return self.module if self.is_package else self.module.rpartition(".")[0]


def count_lines(text: str) -> int:
    """Physical lines: the newline count, plus a final line that has none."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def parse_source(relative: str, text: str) -> SourceFile:
    """Parse ``text`` as the file at POSIX path ``relative`` from the repository root."""
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        raise MetricsError(f"{relative}:{error.lineno}: does not parse: {error.msg}") from error
    parts = relative.removesuffix(".py").split("/")
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return SourceFile(
        relative=relative, module=".".join(parts), is_package=is_package, tree=tree, lines=count_lines(text)
    )


def load_tree(root: Path, directory: str) -> list[SourceFile]:
    """Every ``*.py`` file under ``root/directory``, parsed. An empty tree is an error, not a zero."""
    base = root / directory
    if not base.is_dir():
        raise MetricsError(f"{directory}/ does not exist under {root}")
    sources: list[SourceFile] = []
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in relative.split("/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise MetricsError(f"{relative}: cannot be read: {error}") from error
        sources.append(parse_source(relative, text))
    if not sources:
        raise MetricsError(f"no Python files under {directory}/ in {root}")
    return sources


# --- naming ------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One identifier or reference, located in the source."""

    path: str
    line: int
    name: str


def is_camel_case(name: str) -> bool:
    """``fooBar`` or ``_fooBar``: a lowercase first letter and an uppercase one later."""
    stripped = name.lstrip("_")
    return bool(stripped) and stripped[0].islower() and any(character.isupper() for character in stripped)


def is_cap_words(name: str) -> bool:
    """``CommandSandbox`` or ``_Private``: an uppercase first letter and no underscore after it."""
    stripped = name.lstrip("_")
    return bool(stripped) and stripped[0].isupper() and "_" not in stripped


def _is_override(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "override":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "override":
            return True
    return False


def _parameters(arguments: ast.arguments) -> list[ast.arg]:
    found = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        found.append(arguments.vararg)
    if arguments.kwarg is not None:
        found.append(arguments.kwarg)
    return found


def _outer_declarations(body: Sequence[ast.stmt]) -> set[str]:
    """Names a function body declares ``global`` or ``nonlocal``, nested scopes ignored."""
    names: set[str] = set()
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Global | ast.Nonlocal):
            names.update(node.names)
        elif not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            pending.extend(ast.iter_child_nodes(node))
    return names


class _NamingVisitor(ast.NodeVisitor):
    """Walks one module and records each name in the scope that binds it."""

    def __init__(self, path: str) -> None:
        self._path = path
        #: Open scopes, outermost first: ``("class" | "function", name)``.
        self._scopes: list[tuple[str, str]] = []
        #: Per open function scope, the names that are not its locals.
        self._not_locals: list[set[str]] = []
        self._comprehension_targets = 0
        self._seen: set[tuple[str, str, str]] = set()
        self._class_bound: set[tuple[str, str]] = set()
        self._self_attributes: list[tuple[str, Finding]] = []
        self._findings: dict[str, list[Finding]] = {category: [] for category in NAMING_CATEGORIES}

    def findings(self) -> dict[str, list[Finding]]:
        """The findings, once the module has been visited."""
        for owner, finding in self._self_attributes:
            if (owner, finding.name) not in self._class_bound:
                self._record("instance_attributes", owner, finding.name, finding.line)
        self._self_attributes.clear()
        return self._findings

    def _qualname(self, depth: int | None = None) -> str:
        scopes = self._scopes if depth is None else self._scopes[:depth]
        return ".".join(name for _, name in scopes)

    def _enclosing_class(self) -> str:
        for depth in range(len(self._scopes), 0, -1):
            if self._scopes[depth - 1][0] == "class":
                return self._qualname(depth)
        return self._qualname()

    def _record(self, category: str, owner: str, name: str, line: int) -> None:
        key = (category, owner, name)
        if key not in self._seen:
            self._seen.add(key)
            self._findings[category].append(Finding(self._path, line, name))

    def _bind(self, name: str, line: int) -> None:
        if not self._scopes:
            if is_camel_case(name):
                self._record("module_names", "", name, line)
            return
        owner = self._qualname()
        if self._scopes[-1][0] == "class":
            self._class_bound.add((owner, name))
            if is_camel_case(name):
                self._record("class_attributes", owner, name, line)
        elif name not in self._not_locals[-1] and is_camel_case(name):
            self._record("local_variables", owner, name, line)

    def _enter_function(self, name: str, arguments: ast.arguments, body: Sequence[ast.stmt] | ast.expr) -> None:
        self._scopes.append(("function", name))
        owner = self._qualname()
        parameters = _parameters(arguments)
        not_locals = {parameter.arg for parameter in parameters}
        for parameter in parameters:
            if is_camel_case(parameter.arg):
                self._record("parameters", owner, parameter.arg, parameter.lineno)
        if isinstance(body, ast.expr):
            self._not_locals.append(not_locals)
            self.visit(body)
        else:
            self._not_locals.append(not_locals | _outer_declarations(body))
            for statement in body:
                self.visit(statement)
        self._not_locals.pop()
        self._scopes.pop()

    def _visit_defaults(self, arguments: ast.arguments) -> None:
        # Defaults are evaluated in the enclosing scope, before the function exists.
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if any(character.isupper() for character in node.name) and not _is_override(node):
            self._record("functions", self._qualname(), node.name, node.lineno)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_defaults(node.args)
        self._enter_function(node.name, node.args, node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_defaults(node.args)
        self._enter_function("<lambda>", node.args, node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not is_cap_words(node.name):
            self._record("classes", self._qualname(), node.name, node.lineno)
        for expression in (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)):
            self.visit(expression)
        self._scopes.append(("class", node.name))
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Store):
            return
        if self._comprehension_targets == 0:
            self._bind(node.id, node.lineno)
        elif self._scopes and self._scopes[-1][0] == "function":
            # A comprehension variable belongs to no module or class namespace,
            # but inside a function it is one more local name to rename.
            self._bind(node.id, node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        value = node.value
        assigned = isinstance(node.ctx, ast.Store) and isinstance(value, ast.Name) and value.id == "self"
        if assigned and is_camel_case(node.attr):
            self._self_attributes.append((self._enclosing_class(), Finding(self._path, node.lineno, node.attr)))
        self.generic_visit(node)

    def _visit_comprehension(self, generators: list[ast.comprehension], elements: Iterable[ast.expr]) -> None:
        for generator in generators:
            self._comprehension_targets += 1
            self.visit(generator.target)
            self._comprehension_targets -= 1
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for element in elements:
            self.visit(element)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._bind(node.name, node.lineno)
        self.generic_visit(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._bind(node.rest, node.lineno)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self._visit_aliases(node.names, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._visit_aliases(node.names, node.lineno)

    def _visit_aliases(self, aliases: list[ast.alias], line: int) -> None:
        # ``name as name`` is an explicit re-export: the name was counted where it is defined.
        for alias in aliases:
            if alias.asname is not None and alias.asname != alias.name and is_camel_case(alias.asname):
                self._record("import_aliases", self._qualname(), alias.asname, line)


def analyze_naming(sources: Iterable[SourceFile]) -> dict[str, list[Finding]]:
    """PEP 8 naming violations by category, in source order."""
    merged: dict[str, list[Finding]] = {category: [] for category in NAMING_CATEGORIES}
    for source in sources:
        visitor = _NamingVisitor(source.relative)
        visitor.visit(source.tree)
        for category, findings in visitor.findings().items():
            merged[category].extend(findings)
    return merged


# --- imports -----------------------------------------------------------------


@dataclass(frozen=True)
class ImportReference:
    """One module an import statement loads, and the name it takes from it."""

    #: The module the statement names: ``x`` in ``from x import y`` or ``import x``.
    written: str
    #: The module actually loaded: ``x.y`` when ``y`` is a submodule, otherwise ``x``.
    target: str
    #: The attribute taken from ``target``; ``None`` when the module itself is bound.
    name: str | None


@dataclass(frozen=True)
class ImportStatement:
    line: int
    references: tuple[ImportReference, ...]


@dataclass(frozen=True)
class ImportLocation:
    """Where a counted import statement stands, and what it brings in."""

    path: str
    line: int
    names: tuple[str, ...]


def resolve_relative(package: str, level: int, module: str | None) -> str | None:
    """The absolute module ``from <dots><module> import`` names, or ``None`` above the top package."""
    if level == 0:
        return module
    parts = package.split(".") if package else []
    kept = len(parts) - (level - 1)
    if kept < 1:
        return None
    base = parts[:kept]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def import_statements(source: SourceFile, modules: frozenset[str]) -> list[ImportStatement]:
    """Every import statement in ``source``, with each name resolved against the module index.

    ``from x import y`` loads the submodule ``x.y`` only when that module exists;
    otherwise ``y`` is an attribute of ``x``. The index makes that distinction
    exact instead of guessing from capitalisation.
    """
    statements: list[ImportStatement] = []
    for node in ast.walk(source.tree):
        if isinstance(node, ast.Import):
            references = tuple(ImportReference(alias.name, alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(source.package, node.level, node.module)
            if base is None:
                raise MetricsError(f"{source.relative}:{node.lineno}: relative import climbs above the top package")
            references = tuple(
                ImportReference(base, f"{base}.{alias.name}", None)
                if f"{base}.{alias.name}" in modules
                else ImportReference(base, base, alias.name)
                for alias in node.names
            )
        else:
            continue
        statements.append(ImportStatement(node.lineno, references))
    statements.sort(key=lambda statement: statement.line)
    return statements


def _is_facade(module: str) -> bool:
    return module == FACADE or module.startswith(FACADE_PART_PREFIX)


def _displayed(reference: ImportReference) -> str:
    return reference.target if reference.name is None else reference.name


def facade_imports(
    sources: Iterable[SourceFile], modules: frozenset[str]
) -> tuple[list[ImportLocation], list[ImportLocation]]:
    """Statements importing the facade, and statements importing a subpackage through it."""
    facade: list[ImportLocation] = []
    through_root: list[ImportLocation] = []
    for source in sources:
        if _is_facade(source.module):
            continue
        for statement in import_statements(source, modules):
            names = tuple(_displayed(ref) for ref in statement.references if _is_facade(ref.target))
            if names:
                facade.append(ImportLocation(source.relative, statement.line, names))
                continue
            subpackages = tuple(
                ref.target.rpartition(".")[2]
                for ref in statement.references
                if ref.written == FACADE and ref.name is None and ref.target.startswith(FACADE + ".")
            )
            if subpackages:
                through_root.append(ImportLocation(source.relative, statement.line, subpackages))
    return facade, through_root


@dataclass(frozen=True)
class CompatModule:
    """A compatibility re-export module and the import statements that still load it."""

    module: str
    path: str
    #: Physical lines; ``None`` once the module has been deleted.
    lines: int | None
    production: tuple[ImportLocation, ...]
    tests: tuple[ImportLocation, ...]


def _references_to(module: str, sources: Iterable[SourceFile], modules: frozenset[str]) -> tuple[ImportLocation, ...]:
    found: list[ImportLocation] = []
    for source in sources:
        for statement in import_statements(source, modules):
            names = tuple(_displayed(ref) for ref in statement.references if ref.target == module)
            if names:
                found.append(ImportLocation(source.relative, statement.line, names))
    return tuple(found)


def compat_modules(
    production: Sequence[SourceFile], tests: Sequence[SourceFile], modules: frozenset[str]
) -> list[CompatModule]:
    by_module = {source.module: source for source in production}
    report: list[CompatModule] = []
    for module in COMPAT_MODULES:
        source = by_module.get(module)
        report.append(
            CompatModule(
                module=module,
                path=source.relative if source is not None else module.replace(".", "/") + ".py",
                lines=source.lines if source is not None else None,
                production=_references_to(module, production, modules),
                tests=_references_to(module, tests, modules),
            )
        )
    return report


# --- typing.Any --------------------------------------------------------------

_TYPING_MODULES: Final[frozenset[str]] = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True)
class _TypingNames:
    """The local names one module binds to the typing module and to its members."""

    modules: frozenset[str]
    members: dict[str, frozenset[str]]

    def refers_to(self, node: ast.AST, member: str) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.members.get(member, frozenset())
        if isinstance(node, ast.Attribute) and node.attr == member:
            value = node.value
            return isinstance(value, ast.Name) and value.id in self.modules
        return False


def _typing_names(tree: ast.Module) -> _TypingNames:
    modules: set[str] = set()
    members: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name in _TYPING_MODULES)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in _TYPING_MODULES:
            for alias in node.names:
                members.setdefault(alias.name, set()).add(alias.asname or alias.name)
    return _TypingNames(frozenset(modules), {member: frozenset(names) for member, names in members.items()})


def _type_expression_roots(tree: ast.Module, typing_names: _TypingNames) -> Iterator[ast.expr]:
    """Expressions the type checker reads as types, where a string is a forward reference."""
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation
            if node.value is not None and typing_names.refers_to(node.annotation, "TypeAlias"):
                yield node.value
        elif isinstance(node, ast.TypeAlias):
            yield node.value
        elif isinstance(node, ast.TypeVar) and node.bound is not None:
            yield node.bound
        elif isinstance(node, ast.Call) and node.args and typing_names.refers_to(node.func, "cast"):
            yield node.args[0]


def _forward_references(node: ast.expr, typing_names: _TypingNames) -> Iterator[tuple[int, str]]:
    """String constants of a type expression, except ``Literal`` values and ``Annotated`` metadata."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node.lineno, node.value
        return
    if isinstance(node, ast.Subscript):
        if typing_names.refers_to(node.value, "Literal"):
            return
        if typing_names.refers_to(node.value, "Annotated"):
            index = node.slice
            yield from _forward_references(
                index.elts[0] if isinstance(index, ast.Tuple) and index.elts else index, typing_names
            )
            return
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.expr):
            yield from _forward_references(child, typing_names)


def _any_lines(tree: ast.AST, typing_names: _TypingNames) -> list[int]:
    """The line of each ``Any`` name or ``typing.Any`` attribute under ``tree``."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name | ast.Attribute) and typing_names.refers_to(node, "Any")
    ]


def _any_in_forward_reference(line: int, text: str, typing_names: _TypingNames, path: str) -> list[int]:
    """``Any`` references inside a string type expression that starts on ``line``."""
    try:
        expression = ast.parse(text.strip(), mode="eval").body
    except SyntaxError as error:
        raise MetricsError(f"{path}:{line}: string type expression {text!r} does not parse") from error
    # Positions inside the parsed string count from its own first line.
    found = [line + inner - 1 for inner in _any_lines(expression, typing_names)]
    for inner, nested in _forward_references(expression, typing_names):
        found.extend(_any_in_forward_reference(line + inner - 1, nested, typing_names, path))
    return found


def any_references(source: SourceFile) -> list[Finding]:
    """Every reference to ``typing.Any`` in ``source``, string type expressions included."""
    typing_names = _typing_names(source.tree)
    lines = _any_lines(source.tree, typing_names)
    for root in _type_expression_roots(source.tree, typing_names):
        for line, text in _forward_references(root, typing_names):
            lines.extend(_any_in_forward_reference(line, text, typing_names, source.relative))
    return [Finding(source.relative, line, "Any") for line in sorted(lines)]


# --- mixins and file sizes ---------------------------------------------------


@dataclass(frozen=True)
class Composition:
    """A class that lists mixins among its bases."""

    path: str
    line: int
    name: str
    mixins: tuple[str, ...]


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def find_mixins(sources: Iterable[SourceFile]) -> tuple[list[Finding], list[Composition]]:
    mixins: list[Finding] = []
    compositions: list[Composition] = []
    for source in sources:
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name.endswith("Mixin"):
                mixins.append(Finding(source.relative, node.lineno, node.name))
            bases = tuple(
                name
                for name in (_base_name(base) for base in node.bases)
                if name is not None and name.endswith("Mixin")
            )
            if bases:
                compositions.append(Composition(source.relative, node.lineno, node.name, bases))
    mixins.sort(key=lambda finding: (finding.path, finding.line))
    compositions.sort(key=lambda composition: (composition.path, composition.line))
    return mixins, compositions


@dataclass(frozen=True)
class FileSize:
    path: str
    lines: int


def largest_files(sources: Iterable[SourceFile], top: int) -> list[FileSize]:
    ranked = sorted(sources, key=lambda source: (-source.lines, source.relative))
    return [FileSize(source.relative, source.lines) for source in ranked[:top]]


# --- test collection ---------------------------------------------------------

_COLLECTION_SUMMARY: Final[re.Pattern[str]] = re.compile(r"(?P<count>\d+) tests? collected in \d+(?:\.\d+)?s")


@dataclass(frozen=True)
class CollectedTests:
    count: int
    by_directory: dict[str, int]
    pytest_version: str = ""


def _test_directory(node_id: str) -> str:
    path = node_id.split("::", 1)[0]
    return path.rpartition("/")[0] or path


def parse_collection(output: str) -> CollectedTests:
    """Read ``pytest --collect-only -q`` output: node IDs, a blank line, then ``N tests collected in Xs``.

    The listed IDs and the summary must agree, so a change in pytest's output
    format fails here instead of producing a wrong count.
    """
    head, separator, summary = output.strip("\n").rpartition("\n\n")
    match = _COLLECTION_SUMMARY.fullmatch(summary.strip()) if separator else None
    if match is None:
        raise MetricsError(
            "pytest --collect-only -q output does not end in 'N tests collected in Xs' after a blank line:\n" + output
        )
    node_ids = head.splitlines()
    unexpected = [line for line in node_ids if "::" not in line or line != line.strip()]
    if unexpected:
        raise MetricsError(f"pytest --collect-only -q listed a line that is not a test ID: {unexpected[0]!r}")
    count = int(match["count"])
    if count != len(node_ids):
        raise MetricsError(f"pytest reported {count} collected tests but listed {len(node_ids)} test IDs")
    if count == 0:
        raise MetricsError("pytest collected no tests")
    return CollectedTests(count=count, by_directory=dict(sorted(Counter(map(_test_directory, node_ids)).items())))


def collect_tests(root: Path) -> CollectedTests:
    """Count the tests pytest collects under ``root/tests``, in a separate process."""
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "--color=no", "-p", "no:cacheprovider", TESTS]
    # Options injected from the environment would change what is collected.
    environment = {key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"}
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False, env=environment)
    if result.returncode != 0:
        raise MetricsError(f"pytest collection exited with status {result.returncode}:\n{result.stdout}{result.stderr}")
    return dataclasses.replace(parse_collection(result.stdout), pytest_version=importlib.metadata.version("pytest"))


# --- coverage ----------------------------------------------------------------


@dataclass(frozen=True)
class CoverageCounts:
    statements: int
    missed: int

    @property
    def percent(self) -> float:
        """Covered statements as a percentage; a file without statements is fully covered."""
        if self.statements == 0:
            return 100.0
        return 100.0 * (self.statements - self.missed) / self.statements


@dataclass(frozen=True)
class CoverageReport:
    data_file: str
    coverage_version: str
    total: CoverageCounts
    packages: dict[str, CoverageCounts]


def coverage_package(relative: str) -> str:
    """``super_agent/<package>``, or ``super_agent/runtime/<subpackage>``; top-level modules group as ``super_agent``."""
    parts = relative.split("/")
    if len(parts) <= 2:
        return parts[0]
    if parts[1] == "runtime" and len(parts) >= 4:
        return "/".join(parts[:3])
    return "/".join(parts[:2])


def _shown_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def read_coverage(data_file: Path, root: Path, production: Sequence[SourceFile]) -> CoverageReport:
    """Aggregate an existing coverage data file by package.

    The data must describe exactly the production files of this checkout: a file
    missing from it, or measured but gone, means the data is stale or was not
    collected with ``--cov=super_agent``, and the per-package numbers would be wrong.
    """
    if not data_file.is_file():
        raise MetricsError(f"coverage data file {data_file} does not exist; run ./scripts/coverage.sh first")
    try:
        import coverage
        from coverage.exceptions import CoverageException
    except ImportError as error:
        raise MetricsError(
            "--coverage-file needs the coverage package, which uv sync installs with pytest-cov"
        ) from error
    config = root / "pyproject.toml"
    measurement = coverage.Coverage(data_file=str(data_file), config_file=str(config) if config.is_file() else False)
    try:
        measurement.load()
        measured_files = measurement.get_data().measured_files()
    except CoverageException as error:
        raise MetricsError(f"{data_file}: {error}") from error
    resolved_root = root.resolve()
    measured: dict[str, str] = {}
    for filename in measured_files:
        try:
            relative = Path(filename).resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            continue
        if relative.startswith(f"{PRODUCTION}/"):
            measured[relative] = filename
    if not measured:
        raise MetricsError(f"{data_file} has no data for {PRODUCTION}/ under {root}; it belongs to another checkout")
    expected = {source.relative for source in production}
    absent = sorted(expected - measured.keys())
    if absent:
        raise MetricsError(
            f"{data_file} has no data for {len(absent)} production files, first {absent[0]}; it is stale or was not "
            "collected with --cov=super_agent; regenerate it with ./scripts/coverage.sh"
        )
    gone = sorted(measured.keys() - expected)
    if gone:
        raise MetricsError(
            f"{data_file} measured {len(gone)} files that no longer exist, first {gone[0]}; regenerate it"
        )
    statements_by_package: Counter[str] = Counter()
    missed_by_package: Counter[str] = Counter()
    for relative in sorted(measured):
        try:
            _, statements, _, missing, _ = measurement.analysis2(measured[relative])
        except CoverageException as error:
            raise MetricsError(f"{data_file}: {relative}: {error}") from error
        package = coverage_package(relative)
        statements_by_package[package] += len(statements)
        missed_by_package[package] += len(missing)
    packages = {
        package: CoverageCounts(statements_by_package[package], missed_by_package[package])
        for package in sorted(statements_by_package)
    }
    total = CoverageCounts(sum(statements_by_package.values()), sum(missed_by_package.values()))
    return CoverageReport(
        data_file=_shown_path(data_file, root), coverage_version=coverage.__version__, total=total, packages=packages
    )


# --- cold start --------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """A program a fresh interpreter runs with ``-c``."""

    name: str
    code: str


COLD_START_PROBES: Final[tuple[Probe, ...]] = (
    Probe("interpreter", "pass"),
    Probe("entry_import", "import super_agent.__main__"),
    Probe("terminal_import", "import super_agent.__main__, super_agent.tui"),
)


@dataclass(frozen=True)
class Timing:
    samples_ms: tuple[float, ...]

    @property
    def median_ms(self) -> float:
        return statistics.median(self.samples_ms)

    @property
    def min_ms(self) -> float:
        return min(self.samples_ms)

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms)


@dataclass(frozen=True)
class ColdStart:
    runs: int
    probes: dict[str, Timing]
    skipped: dict[str, str]


def default_probes(platform_name: str = sys.platform) -> tuple[tuple[Probe, ...], dict[str, str]]:
    """The probes this platform can run, and the reason for each one it cannot."""
    if platform_name == "win32":
        kept = tuple(probe for probe in COLD_START_PROBES if probe.name != "terminal_import")
        return kept, {"terminal_import": "the terminal front end is not provided on Windows"}
    return COLD_START_PROBES, {}


def _time_probe(root: Path, probe: Probe) -> float:
    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-c", probe.code], cwd=root, capture_output=True, text=True, check=False)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if result.returncode != 0:
        raise MetricsError(
            f"cold-start probe {probe.name} ({probe.code!r}) exited with status {result.returncode}:\n{result.stderr}"
        )
    return elapsed_ms


def measure_cold_start(
    root: Path, runs: int, probes: Sequence[Probe], skipped: dict[str, str] | None = None
) -> ColdStart:
    """Time ``runs`` fresh processes per probe, interleaved so drift affects every probe alike."""
    if runs < 1:
        raise MetricsError(f"cold-start runs must be at least 1, not {runs}")
    for probe in probes:
        _time_probe(root, probe)
    samples: dict[str, list[float]] = {probe.name: [] for probe in probes}
    for _ in range(runs):
        for probe in probes:
            samples[probe.name].append(_time_probe(root, probe))
    return ColdStart(
        runs=runs,
        probes={name: Timing(tuple(values)) for name, values in samples.items()},
        skipped=dict(skipped or {}),
    )


# --- environment -------------------------------------------------------------


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    except OSError as error:
        raise MetricsError(f"git cannot run: {error}") from error
    if result.returncode != 0:
        raise MetricsError(f"git {' '.join(arguments)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def environment(root: Path) -> dict[str, object]:
    """What a later run needs to reproduce these numbers: the commit, the platform, the interpreter."""
    changes = _git(root, "status", "--porcelain", "--", PRODUCTION, TESTS, "scripts/metrics.py")
    return {
        "git_commit": _git(root, "rev-parse", "HEAD"),
        "git_dirty": bool(changes),
        "date": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
    }


# --- the report --------------------------------------------------------------


@dataclass(frozen=True)
class TreeSummary:
    directory: str
    files: int
    lines: int


@dataclass(frozen=True)
class Report:
    environment: dict[str, object]
    trees: dict[str, TreeSummary]
    naming: dict[str, dict[str, list[Finding]]]
    facade_imports: dict[str, list[ImportLocation]]
    subpackage_imports: dict[str, list[ImportLocation]]
    compat: list[CompatModule]
    any_references: list[Finding]
    mixins: list[Finding]
    compositions: list[Composition]
    largest_files: list[FileSize]
    tests_collected: CollectedTests | None
    coverage: CoverageReport | None
    cold_start: ColdStart | None


@dataclass(frozen=True)
class Options:
    root: Path
    collect_tests: bool
    coverage_file: Path | None
    cold_start_runs: int
    top: int
    json_path: str | None
    markdown_path: str | None


def build_report(options: Options) -> Report:
    """Measure everything ``options`` asks for; the cheap structural checks run first."""
    root = options.root
    production = load_tree(root, PRODUCTION)
    tests = load_tree(root, TESTS)
    provenance = environment(root)
    modules = frozenset(source.module for source in (*production, *tests))
    production_facade, production_through_root = facade_imports(production, modules)
    tests_facade, tests_through_root = facade_imports(tests, modules)
    mixins, compositions = find_mixins(production)
    coverage = read_coverage(options.coverage_file, root, production) if options.coverage_file else None
    tests_collected = collect_tests(root) if options.collect_tests else None
    cold_start = None
    if options.cold_start_runs:
        probes, skipped = default_probes()
        cold_start = measure_cold_start(root, options.cold_start_runs, probes, skipped)
    return Report(
        environment=provenance,
        trees={
            "production": TreeSummary(PRODUCTION, len(production), sum(source.lines for source in production)),
            "tests": TreeSummary(TESTS, len(tests), sum(source.lines for source in tests)),
        },
        naming={"production": analyze_naming(production), "tests": analyze_naming(tests)},
        facade_imports={"production": production_facade, "tests": tests_facade},
        subpackage_imports={"production": production_through_root, "tests": tests_through_root},
        compat=compat_modules(production, tests, modules),
        any_references=[finding for source in production for finding in any_references(source)],
        mixins=mixins,
        compositions=compositions,
        largest_files=largest_files(production, options.top),
        tests_collected=tests_collected,
        coverage=coverage,
        cold_start=cold_start,
    )


def _by_file(findings: Iterable[Finding]) -> dict[str, int]:
    counts = Counter(finding.path for finding in findings)
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _location_json(location: ImportLocation) -> dict[str, object]:
    return {"path": location.path, "line": location.line, "names": list(location.names)}


def _imports_json(locations: Sequence[ImportLocation]) -> dict[str, object]:
    return {"count": len(locations), "locations": [_location_json(location) for location in locations]}


def _timing_json(timing: Timing) -> dict[str, object]:
    return {
        "median_ms": round(timing.median_ms, 1),
        "min_ms": round(timing.min_ms, 1),
        "max_ms": round(timing.max_ms, 1),
        "samples_ms": [round(sample, 1) for sample in timing.samples_ms],
    }


def _coverage_counts_json(counts: CoverageCounts) -> dict[str, object]:
    return {"statements": counts.statements, "missed": counts.missed, "percent": round(counts.percent, 2)}


def report_to_json(report: Report) -> dict[str, object]:
    """The report as JSON-ready data; keys are stable within one ``schema`` version."""
    naming = {
        tree: {
            category: {
                "count": len(findings),
                "names": len({finding.name for finding in findings}),
                "by_file": _by_file(findings),
            }
            for category, findings in categories.items()
        }
        for tree, categories in report.naming.items()
    }
    compat = {
        module.path: {
            "present": module.lines is not None,
            "lines": module.lines or 0,
            "references": {
                "production": [_location_json(location) for location in module.production],
                "tests": [_location_json(location) for location in module.tests],
            },
        }
        for module in report.compat
    }
    tests_collected = None
    if report.tests_collected is not None:
        tests_collected = {
            "count": report.tests_collected.count,
            "by_directory": report.tests_collected.by_directory,
            "pytest": report.tests_collected.pytest_version,
        }
    coverage = None
    if report.coverage is not None:
        coverage = {
            "data_file": report.coverage.data_file,
            "coverage_py": report.coverage.coverage_version,
            "total": _coverage_counts_json(report.coverage.total),
            "packages": {
                package: _coverage_counts_json(counts) for package, counts in report.coverage.packages.items()
            },
        }
    cold_start = None
    if report.cold_start is not None:
        cold_start = {
            "runs": report.cold_start.runs,
            "probes": {name: _timing_json(timing) for name, timing in report.cold_start.probes.items()},
            "skipped": report.cold_start.skipped,
        }
    return {
        "schema": SCHEMA_VERSION,
        "environment": report.environment,
        "trees": {
            name: {"directory": tree.directory, "files": tree.files, "lines": tree.lines}
            for name, tree in report.trees.items()
        },
        "naming": naming,
        "facade_imports": {tree: _imports_json(locations) for tree, locations in report.facade_imports.items()},
        "subpackage_imports_via_facade": {
            tree: _imports_json(locations) for tree, locations in report.subpackage_imports.items()
        },
        "compat_modules": compat,
        "any": {"production": {"count": len(report.any_references), "by_file": _by_file(report.any_references)}},
        "mixins": {
            "production": {
                "mixins": [{"path": m.path, "line": m.line, "name": m.name} for m in report.mixins],
                "composed": [
                    {"path": c.path, "line": c.line, "name": c.name, "mixins": list(c.mixins)}
                    for c in report.compositions
                ],
            }
        },
        "largest_files": {"production": [{"path": size.path, "lines": size.lines} for size in report.largest_files]},
        "tests_collected": tests_collected,
        "coverage": coverage,
        "cold_start": cold_start,
        "definitions": DEFINITIONS,
    }


_NAMING_LABELS: Final[dict[str, str]] = {
    "functions": "Function and method names not in snake_case",
    "classes": "Class names not in CapWords",
    "parameters": "camelCase parameters",
    "local_variables": "camelCase local variables",
    "instance_attributes": "camelCase instance attributes (`self.x = ...`)",
    "class_attributes": "camelCase class-body names (fields)",
    "module_names": "camelCase module-level names",
    "import_aliases": "camelCase import aliases",
}

_NOT_MEASURED: Final[str] = "—"


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def render_markdown(report: Report) -> str:
    """A summary for ``$GITHUB_STEP_SUMMARY``: headline table, then the detail behind it."""
    env = report.environment
    commit = str(env["git_commit"])[:12]
    state = " with uncommitted changes" if env["git_dirty"] else ""
    lines = [
        "## Code metrics",
        "",
        f"Commit `{commit}`{state} · {env['system']} {env['release']} {env['machine']} · "
        f"{env['implementation']} {env['python']} · {env['date']}",
        "",
        _row("Metric", "Production", "Tests"),
        "|---|---:|---:|",
    ]
    production, tests = report.trees["production"], report.trees["tests"]
    lines.append(
        _row("Python files / lines", f"{production.files} / {production.lines:,}", f"{tests.files} / {tests.lines:,}")
    )
    for category in NAMING_CATEGORIES:
        lines.append(
            _row(
                _NAMING_LABELS[category],
                len(report.naming["production"][category]),
                len(report.naming["tests"][category]),
            )
        )
    lines.append(
        _row(
            "Imports of the `super_agent.runtime` facade",
            len(report.facade_imports["production"]),
            len(report.facade_imports["tests"]),
        )
    )
    lines.append(
        _row(
            "`from super_agent.runtime import <subpackage>` (not facade)",
            len(report.subpackage_imports["production"]),
            len(report.subpackage_imports["tests"]),
        )
    )
    lines.append(
        _row(
            "Imports of compatibility modules",
            sum(len(module.production) for module in report.compat),
            sum(len(module.tests) for module in report.compat),
        )
    )
    lines.append(_row("`typing.Any` references", len(report.any_references), _NOT_MEASURED))
    lines.append(_row("Mixin classes", len(report.mixins), _NOT_MEASURED))
    lines.append(_row("Classes composed from mixins", len(report.compositions), _NOT_MEASURED))
    collected = report.tests_collected.count if report.tests_collected is not None else _NOT_MEASURED
    lines.append(_row("Collected tests", _NOT_MEASURED, collected))

    skipped = [
        flag
        for flag, value in (
            ("--collect-tests", report.tests_collected),
            ("--coverage-file", report.coverage),
            ("--cold-start-runs", report.cold_start),
        )
        if value is None
    ]
    if skipped:
        lines.extend(["", "Not measured in this run: " + ", ".join(f"`{flag}`" for flag in skipped) + "."])

    lines.extend(["", "### Compatibility modules", "", _row("Module", "Lines", "Production imports", "Test imports")])
    lines.append("|---|---:|---:|---:|")
    for module in report.compat:
        size = module.lines if module.lines is not None else "removed"
        lines.append(_row(f"`{module.path}`", size, len(module.production), len(module.tests)))

    lines.extend(["", "### Largest production files", "", _row("File", "Lines"), "|---|---:|"])
    lines.extend(_row(f"`{size.path}`", size.lines) for size in report.largest_files)

    if report.coverage is not None:
        lines.extend(["", "### Line coverage by package", ""])
        lines.extend([_row("Package", "Statements", "Missed", "Coverage"), "|---|---:|---:|---:|"])
        for package, counts in report.coverage.packages.items():
            lines.append(_row(f"`{package}`", counts.statements, counts.missed, f"{counts.percent:.1f}%"))
        total = report.coverage.total
        lines.append(_row("**Total**", total.statements, total.missed, f"{total.percent:.1f}%"))

    if report.cold_start is not None:
        lines.extend(["", f"### Cold start ({report.cold_start.runs} runs per probe)", ""])
        lines.extend([_row("Probe", "Median ms", "Min ms", "Max ms"), "|---|---:|---:|---:|"])
        for name, timing in report.cold_start.probes.items():
            lines.append(_row(name, f"{timing.median_ms:.1f}", f"{timing.min_ms:.1f}", f"{timing.max_ms:.1f}"))
        for name, reason in report.cold_start.skipped.items():
            lines.append(_row(name, f"skipped: {reason}", "", ""))

    lines.extend(["", "<details><summary>Definitions</summary>", ""])
    lines.extend(f"- **{key}**: {text}" for key, text in DEFINITIONS.items())
    lines.extend(["", "</details>", ""])
    return "\n".join(lines)


# --- command line ------------------------------------------------------------


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative: {text}")
    return value


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {text}")
    return value


def parse_options(argv: Sequence[str]) -> Options:
    parser = argparse.ArgumentParser(description="Compute the code metrics of the optimisation baseline.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--collect-tests", action="store_true", help="count tests with pytest --collect-only")
    parser.add_argument("--coverage-file", type=Path, help="aggregate this coverage data file by package")
    parser.add_argument(
        "--cold-start-runs", type=_non_negative, default=0, help="time this many fresh processes per probe"
    )
    parser.add_argument("--top", type=_positive, default=DEFAULT_TOP_FILES, help="number of largest files to list")
    parser.add_argument("--json", dest="json_path", help="write JSON to this file, or - for stdout")
    parser.add_argument("--markdown", dest="markdown_path", help="write Markdown to this file, or - for stdout")
    namespace = parser.parse_args(argv)
    coverage_file: Path | None = namespace.coverage_file
    return Options(
        root=Path(namespace.root),
        collect_tests=bool(namespace.collect_tests),
        coverage_file=coverage_file,
        cold_start_runs=int(namespace.cold_start_runs),
        top=int(namespace.top),
        json_path=namespace.json_path,
        markdown_path=namespace.markdown_path,
    )


def _write(target: str, text: str) -> None:
    if target == "-":
        sys.stdout.write(text)
    else:
        Path(target).write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_options(sys.argv[1:] if argv is None else argv)
    try:
        report = build_report(options)
    except MetricsError as error:
        print(f"metrics: {error}", file=sys.stderr)
        return 1
    markdown = render_markdown(report)
    if options.json_path is None and options.markdown_path is None:
        sys.stdout.write(markdown)
    if options.json_path is not None:
        _write(options.json_path, json.dumps(report_to_json(report), indent=2, ensure_ascii=False) + "\n")
    if options.markdown_path is not None:
        _write(options.markdown_path, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
