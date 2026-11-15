"""``docs/spec/config.md`` lists every hook event the loader accepts.

The spec's 扩展 section owns the event names; ``HOOK_EVENTS`` is the loader's
copy. The parser fails loudly when the section or its table changes shape, so a
reformatted document cannot turn the comparison into a no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

from super_agent.app.extensions import HOOK_EVENTS

SPEC_DOCUMENT = Path(__file__).resolve().parents[2] / "docs" / "spec" / "config.md"
SECTION_HEADING = "## 扩展"
TABLE_HEADER = "| 事件 | 触发时机 |"
CODE_SPAN = re.compile(r"`([^`]+)`")


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
        first_cell = line.split("|")[1]
        names = CODE_SPAN.findall(first_cell)
        assert names, f"hook event row without a code-spanned event name: {line!r}"
        events.extend(names)
    assert events, "the hook event table has no rows"
    return events


def test_spec_lists_exactly_the_hook_events_the_loader_accepts() -> None:
    documented = _documented_hook_events()
    assert len(documented) == len(set(documented)), f"duplicate hook events in the spec: {documented}"
    assert set(documented) == set(HOOK_EVENTS)
