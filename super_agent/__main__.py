"""The process entry point.

The startup order is part of the contract, because each step can only be done
once the one before it has succeeded:

1. parse the flags, which is the only step that may exit with status 2;
2. load ``.env`` from the process working directory, ignoring its failure;
3. resolve the configuration, which fails loudly on a bad permission mode, a bad
   sandbox mode, or a provider with no usable credential;
4. build the session, MCP servers, tools, and controllers;
5. run the chosen front end, and close the session on the way out.

The front end is one of two: the terminal, or the local web interface (``-web``).
Naming no flag picks the platform default: the web interface on Windows, which
ships without the terminal, and the terminal elsewhere. Both drive the same
conversation adapter, so the only thing this file decides is which transport
carries it.

Status 1 means "the app refused to start" or "the interface failed"; the app
itself never produces any other status.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import os
import sys
from typing import TYPE_CHECKING, Final

from dotenv import load_dotenv

from super_agent import app, cli, llm, web

if TYPE_CHECKING:
    from super_agent import frontend, runtime

#: The web interface's defaults. Loopback only: the interface can run tools, so
#: binding it to every address would hand that to the local network.
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8765


def main() -> None:
    """Parse the flags, then run the selected front end."""
    try:
        flags = cli.parse(sys.argv[1:])
        port = _port(flags.port)
    except cli.FlagError as error:
        if error.message:
            print(error.message, file=sys.stderr)
        if error.showUsage:
            sys.stderr.write(cli.usage())
        raise SystemExit(error.status) from None

    # Loaded from the process working directory, and never overriding a variable
    # that is already exported: a checked-in .env must not win over the
    # operator's environment. A missing file is not an error.
    with contextlib.suppress(Exception):
        load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)

    try:
        cfg = app.load_config(flags, os.environ.get)
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None
    try:
        status = asyncio.run(run(cfg, flags, port=port))
    except KeyboardInterrupt:
        # Ctrl-C is how a long-running front end is asked to stop, not a failure:
        # the interfaces close their own resources before the interrupt reaches
        # here, so there is nothing left to report.
        status = 0
    raise SystemExit(status)


async def run(cfg: app.Config, flags: app.Flags, *, port: int = DEFAULT_PORT) -> int:
    """Build the session and run the selected interface, returning the exit status."""
    try:
        session, mcpController, agentController, memoryController = await app.new_session_with_extensions(cfg)
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    conversation = app.new_conversation_adapter(
        session, mcpController, agentController, memoryController, sandbox_downgraded=cfg.sandbox_downgraded
    )
    workspace = cfg.workspace
    cwd = cfg.project.root if workspace is None else workspace.get_cwd()
    try:
        selected = select_front_end(flags, sys.platform)
        if selected == "web":
            await web.serve(conversation, host=flags.host or DEFAULT_HOST, port=port)
        else:
            await _run_terminal(cfg, session, conversation, agentController, cwd)
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        # The cleanup runs in a ``finally``, so it also happens on the failure
        # path. That is better hygiene than skipping it, and it changes nothing
        # the user saw.
        with contextlib.suppress(Exception):
            await session.close()
        with contextlib.suppress(Exception):
            await app.waitPendingClosers()
    return 0


def select_front_end(flags: app.Flags, platform: str) -> str:
    """The front end to run: an explicit flag wins, otherwise the platform decides.

    Windows ships without the terminal, so naming no flag opens the web interface
    there; POSIX platforms keep the terminal as the default.
    """
    if flags.web:
        return "web"
    return "web" if platform == "win32" else "terminal"


async def _run_terminal(
    cfg: app.Config,
    session: runtime.Session,
    conversation: frontend.Conversation,
    agentController: app.AgentController,
    cwd: str,
) -> None:
    """Run the interactive CLI.

    Imported here rather than at module scope: the terminal needs POSIX and Rich,
    while the web front end needs neither, and a headless deployment must not fail
    on an import it never uses.
    """
    from super_agent import tui

    profile = agentController.active_profile()
    program = tui.TerminalApplication(
        tui.new(
            conversation,
            tui.StartupInfo(
                model_name=llm.model_display_name(profile.provider, llm.ProviderConfig(model=profile.model)),
                version=importlib.metadata.version("super-agent-py"),
                permission_mode=str(profile.permission_mode),
                no_tools=cfg.no_tools,
                cwd=cwd,
                instruction_paths=tuple(cfg.instruction_sources),
                session_id=str(session.metaID()),
                sandbox=str(cfg.sandbox.mode),
            ),
        )
    )
    await program.run_terminal()


def _port(text: str) -> int:
    """The web port, or a flag error. Ports are validated here, not in the socket."""
    if not text:
        return DEFAULT_PORT
    try:
        port = int(text)
    except ValueError:
        raise cli.FlagError(f'invalid port "{text}": not a number') from None
    if port < 0 or port > 65535:
        raise cli.FlagError(f'invalid port "{port}": out of range 0-65535')
    return port


if __name__ == "__main__":
    main()
