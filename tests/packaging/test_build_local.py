"""The local build script.

The script installs the console script into a dedicated virtual environment and
puts a launcher on ``PATH``. The assertions: the launcher exists, it is
executable, and ``-h`` succeeds without claiming that ``-yolo`` defaults to true.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: The text a help printer emits for a flag whose default is not the zero value.
#: ``-yolo`` defaults to false, so its appearance would mean the flag had been
#: inverted.
FORBIDDEN_HELP_TEXT = "Auto-approve tool execution (default true)"


def test_build_local_script_produces_runnable_binary(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    install_dir = tmp_path / "bin"
    install_dir.mkdir()

    result = subprocess.run(
        ["./scripts/build-local.sh"],
        cwd=repo,
        env={**os.environ, "SUPER_AGENT_INSTALL_DIR": str(install_dir)},
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, f"build-local failed:\n{result.stdout}{result.stderr}"

    binary = install_dir / "super-agent"
    assert binary.exists()
    assert os.access(binary, os.X_OK)

    help_result = subprocess.run([str(binary), "-h"], capture_output=True, text=True, check=False)
    assert help_result.returncode == 0, f"binary -h failed:\n{help_result.stdout}{help_result.stderr}"
    assert FORBIDDEN_HELP_TEXT not in help_result.stdout + help_result.stderr
