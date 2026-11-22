"""PEP 8 names across production code and tests, with no exemptions.

ruff's pep8-naming rules (``N`` in ``pyproject.toml``) check definitions,
arguments, locals, class-body names, module names and import aliases, but they
cannot see an attribute assigned through ``self``. The naming counters of
``scripts/metrics.py`` see every one of these categories, so this test runs them
over both trees and requires each count to be zero.
"""

from __future__ import annotations

from pathlib import Path

from scripts import metrics

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_production_and_test_identifiers_follow_pep8() -> None:
    # load_tree raises when a tree holds no Python file; the anchors also prove
    # that both trees were scanned, not some other, emptier directory.
    sources = [*metrics.load_tree(REPO_ROOT, metrics.PRODUCTION), *metrics.load_tree(REPO_ROOT, metrics.TESTS)]
    scanned = {source.relative for source in sources}
    assert {"super_agent/__main__.py", "tests/architecture/test_naming.py"} <= scanned

    findings = metrics.analyze_naming(sources)

    assert set(findings) == set(metrics.NAMING_CATEGORIES)
    violations = [
        f"{finding.path}:{finding.line}: {category}: {finding.name}"
        for category, items in findings.items()
        for finding in items
    ]
    assert not violations, "identifiers that do not follow PEP 8:\n" + "\n".join(violations)


def test_the_naming_check_sees_attributes_assigned_through_self() -> None:
    # The category ruff cannot check. If this counter went blind, the test above
    # would pass on anything.
    source = metrics.parse_source(
        "super_agent/sample.py",
        "class Sample:\n    def __init__(self) -> None:\n        self.camelCase = 1\n",
    )

    findings = metrics.analyze_naming([source])

    assert [finding.name for finding in findings["instance_attributes"]] == ["camelCase"]
