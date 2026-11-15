"""``docs/spec/config.md`` lists every hook event and command-line flag the code accepts.

The spec owns these names: the 扩展 section lists the hook events the loader
accepts (``HOOK_EVENTS``), and the 命令行参数与环境变量 table lists the flags
``super_agent.cli`` parses (``FLAGS``). Both parsers fail loudly when a section or
its table changes shape, so a reformatted document cannot turn a comparison into a
no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

from super_agent.app.extensions import HOOK_EVENTS
from super_agent.cli import FLAGS

SPEC_DOCUMENT = Path(__file__).resolve().parents[2] / "docs" / "spec" / "config.md"
SECTION_HEADING = "## 扩展"
TABLE_HEADER = "| 事件 | 触发时机 |"
FLAG_SECTION_HEADING = "## 命令行参数与环境变量"
FLAG_TABLE_HEADER = "| 开关 | 效果 |"
CODE_SPAN = re.compile(r"`([^`]+)`")
#: A table cell boundary: a pipe not escaped as ``\\|`` inside a cell.
CELL_BOUNDARY = re.compile(r"(?<!\\)\|")


def _documented_hook_events() -> list[str]:
    text = SPEC_DOCUMENT.read_text(encoding="utf-8")
    assert text.count(SECTION_HEADING + "\n") == 1, f"{SPEC_DOCUMENT} has no single {SECTION_HEADING!r} section"
    section = text.split(SECTION_HEADING + "\n", 1)[1].split("\n## ", 1)[0]
    lines = section.splitlines()
    assert TABLE_HEADER in lines, f"the {SECTION_HEADING!r} section has no hook event table"
    start = lines.index(TABLE_HEADER) + 2
    events: list[str] = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        first_cell = CELL_BOUNDARY.split(line)[1]
        names = CODE_SPAN.findall(first_cell)
        assert names, f"hook event row without a code-spanned event name: {line!r}"
        events.extend(names)
    assert events, "the hook event table has no rows"
    return events


def test_spec_lists_exactly_the_hook_events_the_loader_accepts() -> None:
    documented = _documented_hook_events()
    assert len(documented) == len(set(documented)), f"duplicate hook events in the spec: {documented}"
    assert set(documented) == set(HOOK_EVENTS)


def _documented_flags() -> dict[str, bool]:
    """Each documented flag name, mapped to whether it is a bool flag (no ``<value>``)."""
    text = SPEC_DOCUMENT.read_text(encoding="utf-8")
    heading = FLAG_SECTION_HEADING + "\n"
    assert text.count(heading) == 1, f"{SPEC_DOCUMENT} has no single {FLAG_SECTION_HEADING!r} section"
    lines = text.split(heading, 1)[1].split("\n## ", 1)[0].splitlines()
    assert FLAG_TABLE_HEADER in lines, f"the {FLAG_SECTION_HEADING!r} section has no flag table"
    flags: dict[str, bool] = {}
    for line in lines[lines.index(FLAG_TABLE_HEADER) + 2 :]:
        if not line.startswith("|"):
            break
        names = CODE_SPAN.findall(CELL_BOUNDARY.split(line)[1])
        assert names, f"flag table row without a code-spanned switch: {line!r}"
        switch = names[0]
        if not switch.startswith("--"):
            continue  # environment variables such as ``YOLO=true`` share the table
        name, _, value = switch[2:].partition(" ")
        assert name not in flags, f"flag documented twice: {name}"
        flags[name] = value == ""
    assert flags, "the flag table documents no flags"
    return flags


def test_spec_lists_exactly_the_flags_the_parser_defines() -> None:
    documented = _documented_flags()
    defined = {flag.name: flag.is_bool for flag in FLAGS}
    assert documented == defined
