"""The exit-status vocabulary of a command.

The label table is built from a fixed list of signal names, but not every
platform defines every one of them: Windows has no ``SIGKILL``. Importing the
module is what makes the whole application importable, so the table is built
leniently and these tests pin that down.
"""

# These tables are implementation details of the module under test, and
# pinning their platform-lenient construction is what this file is for.
# pyright: reportPrivateUsage=false
from __future__ import annotations

import signal

from super_agent.tools.commands import _signal_labels, _signal_name, _signal_names


def test_the_table_only_names_signals_this_platform_defines() -> None:
    expected = {number for name, _label in _signal_labels if isinstance(number := getattr(signal, name, None), int)}
    assert set(_signal_names) == expected


def test_every_labelled_signal_is_named_with_a_non_empty_label() -> None:
    assert _signal_names
    for number, label in _signal_names.items():
        assert isinstance(number, int)
        assert label != ""


def test_a_signal_without_a_label_is_still_named() -> None:
    """The table is a preference: an unlisted signal falls back to its enum name."""
    unlisted = next((number for number in range(1, 32) if number not in _signal_names), None)
    if unlisted is None:  # pragma: no cover - a platform that labels every signal
        return
    try:
        expected = signal.Signals(unlisted).name.lower()
    except ValueError:
        expected = str(unlisted)
    assert _signal_name(unlisted) == expected
