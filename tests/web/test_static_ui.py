"""The shipped browser interface keeps its structure, safety and a11y contract.

These checks are deliberately about the static files rather than a browser:
the route tests prove the server sends them, and these prove the page they
describe still has the landmarks, controls and state surfaces the TypeScript
expects. A browser acceptance run remains a separate, manual evidence item.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = REPO_ROOT / "super_agent" / "web" / "static"
INDEX = STATIC_ROOT / "index.html"
STYLE = STATIC_ROOT / "style.css"
SCRIPT = STATIC_ROOT / "app.ts"
BUILT_SCRIPT = STATIC_ROOT / "app.js"

REQUIRED_IDS = {
    "sidebar",
    "sidebar-backdrop",
    "sidebar-close",
    "new-chat",
    "sessions",
    "session-title-top",
    "cwd",
    "model",
    "reasoning",
    "main",
    "menu-toggle",
    "status",
    "status-label",
    "connection",
    "connection-label",
    "connection-banner",
    "error-region",
    "usage",
    "settings",
    "transcript",
    "conversation",
    "approval",
    "input",
    "send",
    "queue",
    "stop",
    "hint",
    "permission",
    "memory",
    "toast",
    "settings-modal",
    "settings-close",
    "settings-cancel",
    "settings-save",
    "settings-provider",
    "settings-key",
    "settings-model",
    "sandbox-warning",
}


class Page(HTMLParser):
    """The parts of the page the script and accessibility rely on."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.scripts: list[dict[str, str]] = []
        self.symbols: set[str] = set()
        self.attributes: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self.tags.append((tag, values))
        self.attributes.append(values)
        if "id" in values:
            self.ids.add(values["id"])
        self.classes.update(values.get("class", "").split())
        if tag == "script":
            self.scripts.append(values)
        if tag == "symbol" and values.get("id", "").startswith("icon-"):
            self.symbols.add(values["id"])


@pytest.fixture(scope="module")
def page() -> Page:
    parser = Page()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser


def test_the_page_has_every_landmark_and_control_the_script_binds(page: Page) -> None:
    missing = REQUIRED_IDS - page.ids
    assert not missing, f"missing element ids: {sorted(missing)}"
    assert "shell" in page.classes
    assert "main" in page.classes
    assert "sidebar" in page.classes
    assert "transcript" in page.classes
    assert "composer" in page.classes


def test_the_page_is_a_module_app_with_an_accessible_conversation(page: Page) -> None:
    modules = [script for script in page.scripts if script.get("type") == "module"]
    assert len(modules) == 1
    assert modules[0].get("src") == "/app.js"

    conversation = next(values for _tag, values in page.tags if values.get("id") == "conversation")
    transcript = next(values for _tag, values in page.tags if values.get("id") == "transcript")
    assert conversation.get("role") == "log"
    assert conversation.get("aria-live") == "polite"
    assert transcript.get("aria-busy") == "true"

    viewport = next(values for values in page.attributes if values.get("name") == "viewport")
    assert "width=device-width" in viewport.get("content", "")

    dialog = next(values for _tag, values in page.tags if values.get("id") == "settings-modal")
    assert dialog.get("role") == "dialog"
    assert dialog.get("aria-modal") == "true"
    assert dialog.get("aria-labelledby") == "settings-title"


def test_icon_only_controls_have_names_and_no_inline_handlers(page: Page) -> None:
    for values in page.attributes:
        assert not any(name.startswith("on") for name in values), values
        assert "style" not in values, values

    for element_id in ("sidebar-close", "menu-toggle", "settings-close"):
        element = next(values for _tag, values in page.tags if values.get("id") == element_id)
        assert element.get("aria-label"), element_id

    # The mobile trigger must announce whether the drawer is open and what it
    # controls; both are maintained by the TypeScript, but the initial state is
    # part of the static contract.
    menu = next(values for _tag, values in page.tags if values.get("id") == "menu-toggle")
    assert menu.get("aria-expanded") == "false"
    assert menu.get("aria-controls") == "sidebar"

    assert {"icon-menu", "icon-send", "icon-stop", "icon-refresh"} <= page.symbols


def test_the_stylesheet_defines_the_visual_and_responsive_contract() -> None:
    css = STYLE.read_text(encoding="utf-8")
    required = (
        "prefers-color-scheme: dark",
        "prefers-reduced-motion: reduce",
        "max-width: 900px",
        "max-width: 640px",
        "body.sidebar-open",
        ":focus-visible",
        ".sr-only",
        "[data-pending]",
        '[aria-current="true"]',
        ".status.awaiting",
        ".tool:not(.msg)",
        "--column-width",
        "--sidebar-width",
        "--radius-container",
    )
    missing = [token for token in required if token not in css]
    assert not missing, f"missing style contract: {missing}"
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert ".status.approval" not in css

    depth = 0
    for char in css:
        depth += int(char == "{")
        depth -= int(char == "}")
        assert depth >= 0
    assert depth == 0


def test_the_typescript_uses_only_the_shared_http_and_event_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for endpoint in (
        "/api/snapshot",
        "/api/config",
        "/api/events",
        "/api/turns",
        "/api/steering",
        "/api/queue",
        "/api/cancel",
        "/api/approvals",
        "/api/permission-mode",
        "/api/providers",
        "/api/memory",
        "/api/sessions",
        "/api/reset",
    ):
        assert endpoint in source, endpoint

    for event in (
        "MessageAppended",
        "TurnFinished",
        "ToolApprovalRequested",
        "ToolApprovalCleared",
        "SteeringAccepted",
        "SteeringWithdrawn",
        "QueuedInputAccepted",
        "QueuedInputWithdrawn",
    ):
        assert f'"{event}"' in source, event


def test_the_browser_script_never_interprets_model_text_as_html() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")
    violations = [token for token in forbidden if token in source]
    assert not violations, f"unsafe DOM APIs: {violations}"

    built = BUILT_SCRIPT.read_text(encoding="utf-8")
    assert "new EventSource" in built
    assert "/api/turns" in built
    assert "QueuedInputAccepted" in built


def test_the_built_browser_script_is_syntactically_valid() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the browser build check requires it")
    result = subprocess.run(
        [node, "--check", str(BUILT_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_web_build_is_locked_and_reproducible() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((REPO_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    config = json.loads((REPO_ROOT / "tsconfig.web.json").read_text(encoding="utf-8"))

    assert package["scripts"]["build:web"] == "tsc -p tsconfig.web.json"
    assert package["scripts"]["check:web"].startswith("tsc -p tsconfig.web.json --noEmit")
    assert lock["lockfileVersion"] == 3
    assert lock["packages"]["node_modules/typescript"]["version"].startswith("5.")
    assert config["compilerOptions"]["strict"] is True
    assert config["include"] == ["super_agent/web/static/app.ts"]
    assert re.search(r'"[^"]*app\.ts"', json.dumps(config)) is not None
