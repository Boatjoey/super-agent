"""What startup does with the sandbox decision where no strict sandbox exists.

How ``sandbox.mode`` resolves is covered in ``test_config.py``; these tests
follow the decision out of configuration. The entry point refuses an explicit
``strict``, an unset or ``off`` mode runs commands unsandboxed, and the config
view every front end reads reports the downgrade, so it is announced rather than
silent. Patching ``sys.platform`` stands in for each platform; Windows is the one
without an implementation.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Final

import pytest

from super_agent import __main__, frontend, llm, web
from super_agent.app.config import Config, Flags, load_config
from super_agent.frontend.wire import config_to_json
from super_agent.llm import ProviderConfig
from super_agent.tools.sandbox import new_command_runner
from tests.fakes.model import ScriptedModel

#: ``sys.platform`` on Windows, which has no strict sandbox implementation.
WINDOWS: Final[str] = "win32"


def write_settings(tmp_path: Path, mode: str | None) -> None:
    """Write the pinned home's ``settings.json``; ``None`` leaves ``sandbox`` out.

    ``tests/conftest.py`` has already pointed the home directory at
    ``tmp_path / "home"``.
    """
    sandbox = "" if mode is None else '"sandbox":{"mode":"' + mode + '"},'
    directory = tmp_path / "home" / ".superagent"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "settings.json").write_text(
        '{"provider":"openai",' + sandbox + '"providers":{"openai":{"api_key":"key","model":"model"}}}',
        encoding="utf-8",
    )


def scripted_model(provider: str, config: ProviderConfig) -> ScriptedModel:
    """Stands in for the provider adapter: no test here talks to a model."""
    return ScriptedModel([])


def test_startup_refuses_an_explicit_strict_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_settings(tmp_path, "strict")
    monkeypatch.setattr(sys, "platform", WINDOWS)
    monkeypatch.setattr(sys, "argv", ["super-agent"])
    started: list[Config] = []

    async def run(cfg: Config, flags: Flags, *, port: int = 0) -> int:
        started.append(cfg)
        return 0

    # Without the refusal the entry point would go on to serve the web page until
    # stopped; standing in for that step turns such a regression into a failure
    # instead of a hang.
    monkeypatch.setattr(__main__, "run", run)

    with pytest.raises(SystemExit) as exit_info:
        __main__.main()

    # Status 1 is "the app refused to start", and the reason reaches the operator.
    assert exit_info.value.code == 1
    assert started == []
    assert "sandbox mode strict is not supported on this platform" in capsys.readouterr().err


@pytest.mark.parametrize("mode", [pytest.param(None, id="unset"), pytest.param("off", id="off")])
def test_commands_run_unsandboxed_when_the_sandbox_is_downgraded_or_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str | None
) -> None:
    write_settings(tmp_path, mode)
    monkeypatch.setattr(sys, "platform", WINDOWS)

    cfg = load_config(Flags())
    runner = new_command_runner(cfg.sandbox, None)

    # Nothing wraps the command, so it runs with the operator's full authority.
    assert runner.sandbox is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "mode", "downgraded"),
    [
        pytest.param(WINDOWS, None, True, id="win32-unset"),
        pytest.param(WINDOWS, "off", False, id="win32-off"),
        pytest.param("darwin", None, False, id="darwin-unset"),
        pytest.param("linux", None, False, id="linux-unset"),
    ],
)
async def test_the_config_view_reports_whether_the_sandbox_was_downgraded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, mode: str | None, downgraded: bool
) -> None:
    """The flag travels from configuration through the entry point to the view."""
    write_settings(tmp_path, mode)
    monkeypatch.setattr(llm, "new_model", scripted_model)
    views: list[frontend.ConfigView] = []

    async def serve(frontend_ports: frontend.FrontendPorts, **_options: object) -> None:
        views.append(frontend_ports.config_view())

    monkeypatch.setattr(web, "serve", serve)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", platform)
        cfg = load_config(Flags(web=True))
        # The view is what is under test. Building tools would construct this
        # machine's own sandbox, whatever platform is being stood in for.
        cfg.no_tools = True
        status = await asyncio.wait_for(__main__.run(cfg, Flags(web=True), port=0), timeout=30)

    assert status == 0
    assert len(views) == 1
    assert views[0].sandbox_downgraded is downgraded
    # The web page reads the same field from the JSON it is sent.
    assert config_to_json(views[0])["sandbox_downgraded"] is downgraded
