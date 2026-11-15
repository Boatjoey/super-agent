"""Every directory that holds tests is one pytest actually enters.

pytest skips any directory matching ``norecursedirs`` without a word. Its
defaults include ``build``, ``dist`` and ``venv``, so a test directory with one of
those names silently drops every test inside it instead of failing.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]


def _test_directories() -> list[Path]:
    return sorted({path.parent for path in TESTS_ROOT.rglob("test_*.py") if "__pycache__" not in path.parts})


def test_the_layout_scan_finds_the_test_directories() -> None:
    directories = _test_directories()
    # A scan that finds nothing would make the check below pass vacuously.
    assert TESTS_ROOT / "architecture" in directories
    assert len(directories) > 1


def test_no_test_directory_is_skipped_by_norecursedirs(pytestconfig: pytest.Config) -> None:
    patterns = [str(pattern) for pattern in pytestconfig.getini("norecursedirs")]
    assert patterns, "norecursedirs is empty, so this check would compare against nothing"

    skipped: list[str] = []
    for directory in _test_directories():
        for part in directory.relative_to(TESTS_ROOT).parts:
            matched = [pattern for pattern in patterns if fnmatch.fnmatch(part, pattern)]
            if matched:
                skipped.append(f"{directory.relative_to(TESTS_ROOT.parent)} (matches {', '.join(matched)})")
    assert not skipped, "pytest never collects these test directories: " + "; ".join(skipped)
