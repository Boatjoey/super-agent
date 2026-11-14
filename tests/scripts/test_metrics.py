"""The code-metrics script behind the optimisation baseline.

Each counter is driven with a source that must be counted and with lookalikes
that must not be, and every parser of foreign output (pytest's collection
summary, coverage data, git) must fail loudly when that output is not shaped as
expected, so a format change can never turn into a silent zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import coverage
import pytest

from scripts import metrics

REPO_ROOT = Path(__file__).resolve().parents[2]


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


def naming_of(text: str) -> dict[str, list[str]]:
    source = metrics.parse_source("super_agent/sample.py", textwrap.dedent(text).lstrip("\n"))
    findings = metrics.analyze_naming([source])
    return {category: [finding.name for finding in items] for category, items in findings.items()}


def lines_of(locations: list[metrics.ImportLocation] | tuple[metrics.ImportLocation, ...]) -> list[tuple[str, int]]:
    return [(location.path, location.line) for location in locations]


def git(root: Path, *arguments: str) -> None:
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        ["git", "-c", "user.name=metrics", "-c", "user.email=metrics@example.invalid", *arguments],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )


# --- naming ------------------------------------------------------------------


def test_function_names_count_each_non_snake_case_definition_once_per_scope() -> None:
    names = naming_of(
        """
        import typing

        def fooBar(): ...
        def _privateHelper(): ...
        def snake_case(): ...

        class Box:
            def __init__(self): ...
            def runTurn(self): ...
            @property
            def isOpen(self): ...
            @isOpen.setter
            def isOpen(self, value): ...
            @override
            def visitNode(self): ...
            @typing.override
            def emitEvent(self): ...
            async def waitForIt(self): ...
        """
    )

    assert names["functions"] == ["fooBar", "_privateHelper", "runTurn", "isOpen", "waitForIt"]


def test_class_names_must_be_cap_words() -> None:
    names = naming_of(
        """
        class command_sandbox: ...
        class closerFunc: ...
        class Foo_Bar: ...
        class _private_thing: ...
        class CommandSandbox: ...
        class _Private: ...
        class HTTPServer: ...
        """
    )

    assert names["classes"] == ["command_sandbox", "closerFunc", "Foo_Bar", "_private_thing"]


def test_parameters_of_functions_and_lambdas_are_counted() -> None:
    names = naming_of(
        """
        def configure(settingsPath, plain, /, *extraArgs, autoApprove=True, snake_case=None, **moreOptions): ...

        handler = lambda eventName: eventName
        """
    )

    assert sorted(names["parameters"]) == ["autoApprove", "eventName", "extraArgs", "moreOptions", "settingsPath"]
    assert names["local_variables"] == []


def test_local_variables_cover_every_binding_form_once_per_function() -> None:
    names = naming_of(
        """
        import contextlib

        def work(items, keepNewest):
            toolRunner = 1
            toolRunner = 2
            keepNewest = 4
            for latestTool in items:
                pass
            with contextlib.suppress(Exception) as suppressedError:
                pass
            try:
                pass
            except Exception as hookError:
                pass
            if (matchedItem := items):
                pass
            names = [itemName for itemName in items]
            match items:
                case [firstItem, *restItems]:
                    pass
                case {"key": 1, **extraKeys}:
                    pass
                case str() as textValue:
                    pass
            MAX_SIZE = 3
            Handler = object
            def inner():
                nonlocal toolRunner
                toolRunner = 3
            return names, inner, MAX_SIZE, Handler
        """
    )

    assert names["local_variables"] == [
        "toolRunner",
        "latestTool",
        "suppressedError",
        "hookError",
        "matchedItem",
        "itemName",
        "firstItem",
        "restItems",
        "extraKeys",
        "textValue",
    ]
    # Reassigning a parameter does not make a second identifier.
    assert names["parameters"] == ["keepNewest"]


def test_global_names_count_at_module_scope_not_as_locals() -> None:
    names = naming_of(
        """
        moduleCounter = 0

        def bump():
            global moduleCounter
            moduleCounter += 1
        """
    )

    assert names["module_names"] == ["moduleCounter"]
    assert names["local_variables"] == []


def test_comprehension_variables_outside_functions_bind_no_names() -> None:
    names = naming_of(
        """
        squares = [rootValue * rootValue for rootValue in range(3)]

        class Table:
            cells = {cellKey: 0 for cellKey in "ab"}
        """
    )

    assert names["module_names"] == []
    assert names["class_attributes"] == []


def test_instance_attributes_exclude_names_the_class_body_declares() -> None:
    names = naming_of(
        """
        import dataclasses
        from typing import ClassVar

        @dataclasses.dataclass
        class Model:
            historyIndex: int = 0
            KIND: ClassVar[str] = "model"

            def move(self, other):
                self.historyIndex += 1
                self.turnRunning = True
                self.turnRunning = False
                self.plain_name = 1
                self.first, self.secondItem = 1, 2
                self.typedValue: int = 3
                other.outsideName = 3
                del self.ghostName

        class Other:
            def __init__(self):
                self.turnRunning = 1
        """
    )

    assert names["instance_attributes"] == ["turnRunning", "secondItem", "typedValue", "turnRunning"]
    assert names["class_attributes"] == ["historyIndex"]


def test_module_names_skip_constants_and_type_aliases() -> None:
    names = naming_of(
        """
        slashCommands = []
        _pendingCloses: set[str] = set()
        DEFAULT_PORT = 1
        JSONValue = dict
        __all__ = []
        logger = None
        type InputReader = int
        for loopVariable in range(2):
            pass
        """
    )

    assert names["module_names"] == ["slashCommands", "_pendingCloses", "loopVariable"]


def test_import_aliases_ignore_explicit_reexports() -> None:
    names = naming_of(
        """
        import json as jsonModule
        import numpy as np
        from os.path import join as joinPath
        from package import Thing as OtherThing
        from package import fooBar as fooBar
        """
    )

    assert names["import_aliases"] == ["jsonModule", "joinPath"]


def test_snake_case_module_has_no_naming_findings() -> None:
    names = naming_of(
        """
        MAX_ITEMS = 3

        class Store:
            kind = "store"

            def __init__(self, root_path):
                self.root_path = root_path

            def load(self, item_id):
                found_items = [entry for entry in range(item_id)]
                return found_items
        """
    )

    assert all(found == [] for found in names.values())


# --- imports -----------------------------------------------------------------

FACADE_TREE = {
    "super_agent/__init__.py": "",
    "super_agent/runtime/__init__.py": "from super_agent.runtime.api_engine import Engine as Engine\n",
    "super_agent/runtime/api_engine.py": "from super_agent.runtime.engine import Engine as Engine\n",
    "super_agent/runtime/engine/__init__.py": "class Engine: ...\n",
    "super_agent/runtime/machine/__init__.py": "STATE = 1\n",
    "super_agent/app/__init__.py": "",
    "super_agent/app/config.py": """
        from typing import TYPE_CHECKING
        from super_agent.runtime import Engine
        from super_agent import runtime
        import super_agent.runtime as rt
        from ..runtime import Engine as RelativeEngine
        from super_agent.runtime.api_engine import Engine as PartEngine
        from super_agent.runtime import machine
        from super_agent.runtime.machine import STATE
        import super_agent.runtime.machine
        if TYPE_CHECKING:
            from super_agent.runtime import Engine as TypedEngine
        """,
    "tests/__init__.py": "",
    "tests/test_sample.py": """
        from super_agent.runtime import machine
        from super_agent.runtime import Engine
        """,
}


def test_facade_imports_count_every_form_and_skip_the_facade_itself(tmp_path: Path) -> None:
    write_tree(tmp_path, FACADE_TREE)
    production = metrics.load_tree(tmp_path, "super_agent")
    tests = metrics.load_tree(tmp_path, "tests")
    modules = frozenset(source.module for source in (*production, *tests))

    facade, through_root = metrics.facade_imports(production, modules)
    tests_facade, tests_through_root = metrics.facade_imports(tests, modules)

    config = "super_agent/app/config.py"
    assert lines_of(facade) == [(config, 2), (config, 3), (config, 4), (config, 5), (config, 6), (config, 11)]
    assert [location.names for location in facade[:2]] == [("Engine",), ("super_agent.runtime",)]
    assert lines_of(through_root) == [(config, 7)]
    assert through_root[0].names == ("machine",)
    assert lines_of(tests_facade) == [("tests/test_sample.py", 2)]
    assert lines_of(tests_through_root) == [("tests/test_sample.py", 1)]


def test_relative_import_above_the_top_package_is_an_error(tmp_path: Path) -> None:
    write_tree(tmp_path, {"tests/__init__.py": "", "tests/test_escape.py": "from ... import anything\n"})
    tests = metrics.load_tree(tmp_path, "tests")

    with pytest.raises(metrics.MetricsError, match="climbs above the top package"):
        metrics.facade_imports(tests, frozenset())


COMPAT_TREE = {
    "super_agent/__init__.py": "",
    "super_agent/app/__init__.py": "from super_agent.app.workflows import Runner as Runner\n",
    "super_agent/app/workflows.py": "from super_agent.application.workflows import Runner as Runner\n",
    "super_agent/app/helpers.py": "",
    "super_agent/app/session.py": """
        from super_agent.app import workflows
        import super_agent.app.workflows as compat
        from super_agent.application.workflows import Runner
        from super_agent.app import helpers
        """,
    "super_agent/application/__init__.py": "",
    "super_agent/application/workflows.py": "class Runner: ...\n",
    "super_agent/runtime/__init__.py": "",
    "super_agent/runtime/machine/__init__.py": "from .aliases import Message as Message\n",
    "super_agent/runtime/machine/aliases.py": "Message = str\n",
    "tests/__init__.py": "",
    "tests/test_app.py": "from super_agent.app.workflows import Runner\n",
}


def test_compat_module_references_follow_every_import_form(tmp_path: Path) -> None:
    write_tree(tmp_path, COMPAT_TREE)
    production = metrics.load_tree(tmp_path, "super_agent")
    tests = metrics.load_tree(tmp_path, "tests")
    modules = frozenset(source.module for source in (*production, *tests))

    report = {module.module: module for module in metrics.compat_modules(production, tests, modules)}

    workflows = report["super_agent.app.workflows"]
    assert workflows.lines == 1
    assert lines_of(workflows.production) == [
        ("super_agent/app/__init__.py", 1),
        ("super_agent/app/session.py", 1),
        ("super_agent/app/session.py", 2),
    ]
    assert lines_of(workflows.tests) == [("tests/test_app.py", 1)]
    aliases = report["super_agent.runtime.machine.aliases"]
    assert lines_of(aliases.production) == [("super_agent/runtime/machine/__init__.py", 1)]
    assert aliases.production[0].names == ("Message",)


def test_deleted_compat_module_is_reported_as_removed(tmp_path: Path) -> None:
    write_tree(tmp_path, COMPAT_TREE)
    production = metrics.load_tree(tmp_path, "super_agent")
    tests = metrics.load_tree(tmp_path, "tests")
    modules = frozenset(source.module for source in (*production, *tests))

    report = {module.module: module for module in metrics.compat_modules(production, tests, modules)}

    removed = report["super_agent.app.tui_adapter"]
    assert removed.lines is None
    assert removed.path == "super_agent/app/tui_adapter.py"
    assert removed.production == ()
    assert removed.tests == ()


# --- typing.Any --------------------------------------------------------------


def any_lines(text: str) -> list[int]:
    source = metrics.parse_source("super_agent/sample.py", textwrap.dedent(text).lstrip("\n"))
    return [finding.line for finding in metrics.any_references(source)]


def test_any_references_include_string_type_expressions() -> None:
    lines = any_lines(
        '''
        """Any value is fine here: this docstring is prose."""
        import typing
        import typing as t
        from typing import Annotated, Any, Literal, cast
        from typing import Any as Anything

        # Any in a comment is not code.
        type JSON = dict[str, Any]
        Alias: typing.TypeAlias = "list[Any]"

        def load(raw: Any, extra: "Mapping[str, Any]") -> dict[str, Any]:
            value = cast("Mapping[Any, Any]", raw)
            other = cast(dict[str, t.Any], raw)
            label: Literal["Any"] = "Any"
            note: Annotated[Anything, "Any metadata"]
            return {"Any": value, "other": other, "label": label, "note": note}
        '''
    )

    assert lines == [8, 9, 11, 11, 11, 12, 12, 13, 15]


def test_any_without_a_typing_import_is_not_typing_any() -> None:
    lines = any_lines(
        """
        class Any: ...

        def echo(value: Any) -> Any:
            return value
        """
    )

    assert lines == []


def test_unparsable_string_type_expression_is_an_error() -> None:
    source = metrics.parse_source("super_agent/sample.py", 'def broken(value: "list[") -> None: ...\n')

    with pytest.raises(metrics.MetricsError, match=r"super_agent/sample.py:1: string type expression"):
        metrics.any_references(source)


# --- mixins, sizes, sources ----------------------------------------------------


def test_mixins_and_the_classes_composed_from_them() -> None:
    source = metrics.parse_source(
        "super_agent/engine.py",
        textwrap.dedent(
            """
            class CommandsMixin: ...
            class QueryMixin: ...
            class Mixer: ...
            class Engine(CommandsMixin, base.QueryMixin, Generic[T]): ...
            class Plain(Mixer): ...
            class Typed(QueryMixin[int]): ...
            """
        ).lstrip("\n"),
    )

    mixins, compositions = metrics.find_mixins([source])

    assert [mixin.name for mixin in mixins] == ["CommandsMixin", "QueryMixin"]
    assert [(composition.name, composition.mixins) for composition in compositions] == [
        ("Engine", ("CommandsMixin", "QueryMixin")),
        ("Typed", ("QueryMixin",)),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a", 1), ("a\n", 1), ("a\nb", 2), ("a\n\n", 2)],
)
def test_count_lines_matches_wc_for_terminated_files(text: str, expected: int) -> None:
    assert metrics.count_lines(text) == expected


def test_largest_files_rank_by_lines_then_path() -> None:
    sources = [
        metrics.parse_source("super_agent/b.py", "x = 1\n" * 3),
        metrics.parse_source("super_agent/a.py", "x = 1\n" * 3),
        metrics.parse_source("super_agent/c.py", "x = 1\n" * 5),
        metrics.parse_source("super_agent/d.py", "x = 1\n"),
    ]

    ranked = metrics.largest_files(sources, top=3)

    assert [(size.path, size.lines) for size in ranked] == [
        ("super_agent/c.py", 5),
        ("super_agent/a.py", 3),
        ("super_agent/b.py", 3),
    ]


def test_missing_or_empty_tree_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(metrics.MetricsError, match="does not exist"):
        metrics.load_tree(tmp_path, "super_agent")
    (tmp_path / "super_agent").mkdir()
    (tmp_path / "super_agent" / "README.md").write_text("not python\n", encoding="utf-8")
    with pytest.raises(metrics.MetricsError, match="no Python files"):
        metrics.load_tree(tmp_path, "super_agent")


def test_module_that_does_not_parse_is_an_error(tmp_path: Path) -> None:
    write_tree(tmp_path, {"super_agent/__init__.py": "", "super_agent/broken.py": "def broken(:\n"})

    with pytest.raises(metrics.MetricsError, match=r"super_agent/broken.py:1: does not parse"):
        metrics.load_tree(tmp_path, "super_agent")


# --- test collection -----------------------------------------------------------

COLLECTION_OUTPUT = """\
tests/app/test_config.py::test_loads
tests/app/test_config.py::test_saves[json]
tests/runtime/test_engine.py::test_runs
tests/test_root.py::test_root

4 tests collected in 0.42s
"""


def test_collection_output_is_counted_by_directory() -> None:
    collected = metrics.parse_collection(COLLECTION_OUTPUT)

    assert collected.count == 4
    assert collected.by_directory == {"tests": 1, "tests/app": 2, "tests/runtime": 1}


@pytest.mark.parametrize(
    "output",
    [
        COLLECTION_OUTPUT.replace("4 tests", "5 tests"),
        COLLECTION_OUTPUT.replace("4 tests collected in 0.42s", "collected 4 items"),
        COLLECTION_OUTPUT.replace("\n\n4 tests", "\n4 tests"),
        "WARNING something changed\n" + COLLECTION_OUTPUT,
        "\nno tests collected in 0.01s\n",
        "\n0 tests collected in 0.01s\n",
    ],
    ids=["count-mismatch", "unknown-summary", "no-blank-line", "foreign-line", "no-tests", "zero-tests"],
)
def test_unexpected_collection_output_is_an_error(output: str) -> None:
    with pytest.raises(metrics.MetricsError):
        metrics.parse_collection(output)


def collection_tree(root: Path, test_module: str) -> None:
    write_tree(
        root,
        {
            "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            "tests/__init__.py": "",
            "tests/test_sample.py": test_module,
        },
    )


def test_collect_tests_runs_pytest_in_the_given_root(tmp_path: Path) -> None:
    collection_tree(
        tmp_path,
        """
        import pytest

        def test_single() -> None:
            pass

        @pytest.mark.parametrize("value", [1, 2, 3])
        def test_each(value: int) -> None:
            assert value
        """,
    )

    collected = metrics.collect_tests(tmp_path)

    assert collected.count == 4
    assert collected.by_directory == {"tests": 4}
    assert collected.pytest_version == pytest.__version__


def test_collection_errors_are_reported(tmp_path: Path) -> None:
    collection_tree(tmp_path, "import module_that_does_not_exist\n")

    with pytest.raises(metrics.MetricsError, match="pytest collection exited with status"):
        metrics.collect_tests(tmp_path)


# --- coverage ------------------------------------------------------------------

COVERAGE_TREE = {
    "super_agent/__init__.py": "",
    "super_agent/cli.py": "a = 1\nb = 2\n",
    "super_agent/app/__init__.py": "",
    "super_agent/app/config.py": "x = 1\ny = 2\nz = 3\n",
    "super_agent/runtime/__init__.py": "r = 1\n",
    "super_agent/runtime/machine/__init__.py": "",
    "super_agent/runtime/machine/state.py": "s = 1\nt = 2\n",
}

COVERAGE_EXECUTED = {
    "super_agent/cli.py": [1, 2],
    "super_agent/app/config.py": [1],
    "super_agent/runtime/machine/state.py": [1, 2],
}


def write_coverage(data_file: Path, root: Path, files: list[str]) -> None:
    """Coverage data as ``--cov`` leaves it: executed lines, and never-imported files touched."""
    data = coverage.CoverageData(basename=str(data_file))
    data.add_lines({str(root / relative): lines for relative, lines in COVERAGE_EXECUTED.items() if relative in files})
    data.touch_files([str(root / relative) for relative in files])
    data.write()


def test_coverage_is_aggregated_by_package(tmp_path: Path) -> None:
    write_tree(tmp_path, COVERAGE_TREE)
    write_coverage(tmp_path / ".coverage", tmp_path, list(COVERAGE_TREE))
    production = metrics.load_tree(tmp_path, "super_agent")

    report = metrics.read_coverage(tmp_path / ".coverage", tmp_path, production)

    assert {package: (counts.statements, counts.missed) for package, counts in report.packages.items()} == {
        "super_agent": (2, 0),
        "super_agent/app": (3, 2),
        "super_agent/runtime": (1, 1),
        "super_agent/runtime/machine": (2, 0),
    }
    assert (report.total.statements, report.total.missed) == (8, 3)
    assert report.total.percent == pytest.approx(62.5)
    assert report.data_file == ".coverage"


def test_missing_coverage_file_is_an_error(tmp_path: Path) -> None:
    write_tree(tmp_path, COVERAGE_TREE)
    production = metrics.load_tree(tmp_path, "super_agent")

    with pytest.raises(metrics.MetricsError, match="does not exist"):
        metrics.read_coverage(tmp_path / ".coverage", tmp_path, production)


def test_coverage_data_missing_a_production_file_is_stale(tmp_path: Path) -> None:
    write_tree(tmp_path, COVERAGE_TREE)
    write_coverage(tmp_path / ".coverage", tmp_path, [path for path in COVERAGE_TREE if path != "super_agent/cli.py"])
    production = metrics.load_tree(tmp_path, "super_agent")

    with pytest.raises(metrics.MetricsError, match=r"no data for 1 production files, first super_agent/cli.py"):
        metrics.read_coverage(tmp_path / ".coverage", tmp_path, production)


def test_coverage_data_for_a_deleted_file_is_stale(tmp_path: Path) -> None:
    write_tree(tmp_path, COVERAGE_TREE)
    write_coverage(tmp_path / ".coverage", tmp_path, list(COVERAGE_TREE))
    (tmp_path / "super_agent" / "cli.py").unlink()
    production = metrics.load_tree(tmp_path, "super_agent")

    with pytest.raises(metrics.MetricsError, match="no longer exist"):
        metrics.read_coverage(tmp_path / ".coverage", tmp_path, production)


def test_coverage_data_of_another_checkout_is_an_error(tmp_path: Path) -> None:
    checkout, other = tmp_path / "checkout", tmp_path / "other"
    write_tree(checkout, COVERAGE_TREE)
    write_tree(other, COVERAGE_TREE)
    write_coverage(checkout / ".coverage", other, list(COVERAGE_TREE))
    production = metrics.load_tree(checkout, "super_agent")

    with pytest.raises(metrics.MetricsError, match="another checkout"):
        metrics.read_coverage(checkout / ".coverage", checkout, production)


@pytest.mark.parametrize(
    ("relative", "package"),
    [
        ("super_agent/cli.py", "super_agent"),
        ("super_agent/tui/commands/model.py", "super_agent/tui"),
        ("super_agent/runtime/api_engine.py", "super_agent/runtime"),
        ("super_agent/runtime/machine/state.py", "super_agent/runtime/machine"),
    ],
)
def test_coverage_package_groups_runtime_by_subpackage(relative: str, package: str) -> None:
    assert metrics.coverage_package(relative) == package


# --- cold start ----------------------------------------------------------------


def test_cold_start_times_each_probe_the_requested_number_of_times(tmp_path: Path) -> None:
    cold_start = metrics.measure_cold_start(tmp_path, 2, [metrics.Probe("noop", "pass")], {"other": "reason"})

    timing = cold_start.probes["noop"]
    assert cold_start.runs == 2
    assert len(timing.samples_ms) == 2
    assert 0 < timing.min_ms <= timing.median_ms <= timing.max_ms
    assert cold_start.skipped == {"other": "reason"}


def test_failing_cold_start_probe_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(metrics.MetricsError, match="exited with status 3"):
        metrics.measure_cold_start(tmp_path, 1, [metrics.Probe("broken", "raise SystemExit(3)")])


def test_cold_start_needs_at_least_one_run(tmp_path: Path) -> None:
    with pytest.raises(metrics.MetricsError, match="at least 1"):
        metrics.measure_cold_start(tmp_path, 0, [metrics.Probe("noop", "pass")])


def test_terminal_probe_is_skipped_where_the_terminal_is_not_provided() -> None:
    windows_probes, windows_skipped = metrics.default_probes("win32")
    linux_probes, linux_skipped = metrics.default_probes("linux")

    assert "terminal_import" not in [probe.name for probe in windows_probes]
    assert set(windows_skipped) == {"terminal_import"}
    assert [probe.name for probe in linux_probes] == ["interpreter", "entry_import", "terminal_import"]
    assert linux_skipped == {}


# --- end to end ----------------------------------------------------------------

E2E_TREE = {
    "super_agent/__init__.py": "",
    "super_agent/runtime/__init__.py": "from super_agent.runtime.machine import STATE as STATE\n",
    "super_agent/runtime/machine/__init__.py": "STATE = 1\n",
    "super_agent/app/__init__.py": "",
    "super_agent/app/workflows.py": "from super_agent.runtime import STATE as STATE\n",
    "super_agent/app/config.py": """
        from typing import Any

        from super_agent.app.workflows import STATE

        class LoaderMixin: ...

        class Loader(LoaderMixin):
            def loadAll(self, rawValue: Any) -> Any:
                self.lastValue = rawValue
                return STATE
        """,
    "tests/__init__.py": "",
    "tests/test_config.py": "from super_agent.runtime import machine\n\n\ndef test_config() -> None:\n    assert machine\n",
}


def test_main_writes_json_and_markdown_for_a_git_checkout(tmp_path: Path) -> None:
    write_tree(tmp_path, E2E_TREE)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "fixture")
    json_path, markdown_path = tmp_path / "out.json", tmp_path / "out.md"

    status = metrics.main(["--root", str(tmp_path), "--json", str(json_path), "--markdown", str(markdown_path)])

    assert status == 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["schema"] == metrics.SCHEMA_VERSION
    assert data["environment"]["git_dirty"] is False
    assert len(data["environment"]["git_commit"]) == 40
    assert data["trees"]["production"]["files"] == 6
    naming = data["naming"]["production"]
    assert naming["functions"] == {"count": 1, "names": 1, "by_file": {"super_agent/app/config.py": 1}}
    assert naming["parameters"]["count"] == 1
    assert naming["instance_attributes"]["count"] == 1
    assert data["facade_imports"]["production"]["count"] == 1
    assert data["subpackage_imports_via_facade"]["tests"]["count"] == 1
    workflows = data["compat_modules"]["super_agent/app/workflows.py"]
    assert workflows["present"] is True
    assert len(workflows["references"]["production"]) == 1
    assert data["compat_modules"]["super_agent/app/tui_adapter.py"]["present"] is False
    assert data["any"]["production"]["count"] == 2
    assert [mixin["name"] for mixin in data["mixins"]["production"]["mixins"]] == ["LoaderMixin"]
    assert data["tests_collected"] is None
    assert data["coverage"] is None
    assert data["cold_start"] is None
    assert set(data["definitions"]) >= {"functions", "facade_imports", "any", "coverage", "cold_start"}
    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown.startswith("## Code metrics\n")
    assert "| Metric | Production | Tests |" in markdown
    assert "Not measured in this run: `--collect-tests`, `--coverage-file`, `--cold-start-runs`." in markdown


def test_uncommitted_changes_mark_the_report_dirty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_tree(tmp_path, E2E_TREE)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "fixture")
    (tmp_path / "super_agent" / "extra.py").write_text("x = 1\n", encoding="utf-8")

    status = metrics.main(["--root", str(tmp_path), "--json", "-"])

    assert status == 0
    data = json.loads(capsys.readouterr().out)
    assert data["environment"]["git_dirty"] is True
    assert data["trees"]["production"]["files"] == 7


def test_main_prints_markdown_when_no_output_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_tree(tmp_path, E2E_TREE)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "fixture")

    assert metrics.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("## Code metrics\n")


def test_root_that_is_not_a_git_checkout_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_tree(tmp_path, E2E_TREE)

    assert metrics.main(["--root", str(tmp_path)]) == 1
    assert "metrics: git" in capsys.readouterr().err


def test_root_without_sources_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert metrics.main(["--root", str(tmp_path)]) == 1
    assert "metrics: super_agent/ does not exist" in capsys.readouterr().err


def test_script_runs_as_a_program(tmp_path: Path) -> None:
    write_tree(tmp_path, E2E_TREE)
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "fixture")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "metrics.py"), "--root", str(tmp_path), "--json", "-"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema"] == metrics.SCHEMA_VERSION


def test_static_metrics_cover_the_real_repository() -> None:
    production = metrics.load_tree(REPO_ROOT, "super_agent")
    tests = metrics.load_tree(REPO_ROOT, "tests")
    modules = frozenset(source.module for source in (*production, *tests))

    naming = metrics.analyze_naming(production)
    metrics.facade_imports(production, modules)
    compat = metrics.compat_modules(production, tests, modules)
    for source in production:
        metrics.any_references(source)

    assert "super_agent.__main__" in modules
    assert set(naming) == set(metrics.NAMING_CATEGORIES)
    assert [module.module for module in compat] == list(metrics.COMPAT_MODULES)
    assert all(module.lines is None or module.lines > 0 for module in compat)
