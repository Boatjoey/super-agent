"""Who may use the web interface, exercised without a socket.

The access check is a pure function of a request, so each rule of
``docs/spec/application-interface.md#web-访问认证`` is asserted here directly;
``test_server.py`` proves the server applies it to every request it reads.
"""

from __future__ import annotations

import json
import re

import pytest

from super_agent.web import Request, Response, WebAccess
from super_agent.web.access import LOOPBACK_HOSTS, UNAUTHENTICATED, new_token

TOKEN = "launch-token-for-tests"
PORT = 8765
HOST = f"127.0.0.1:{PORT}"
COOKIE = f"super_agent_{PORT}={TOKEN}"
PAGE = b"<!doctype html><p>open the address printed at startup</p>"


def access(host: str = "127.0.0.1", *, port: int = PORT, bound: tuple[str, ...] = ()) -> WebAccess:
    return WebAccess(TOKEN, host=host, port=port, bound=bound, page=PAGE)


def request(
    path: str = "/api/snapshot",
    *,
    method: str = "GET",
    host: str | None = HOST,
    origin: str | None = None,
    cookie: str | None = None,
    query: dict[str, list[str]] | None = None,
) -> Request:
    headers: dict[str, str] = {}
    if host is not None:
        headers["host"] = host
    if origin is not None:
        headers["origin"] = origin
    if cookie is not None:
        headers["cookie"] = cookie
    return Request(method=method, path=path, query=query or {}, headers=headers)


def header(response: Response, name: str) -> str | None:
    values = [value for key, value in response.headers if key.lower() == name.lower()]
    assert len(values) <= 1, f"{name} appears more than once"
    return values[0] if values else None


def error_of(response: Response) -> str:
    assert response.content_type.startswith("application/json")
    return str(json.loads(response.body)["error"])


def refused(check: Response | None, status: int) -> Response:
    """The refusal ``check`` returned, after asserting it is one with ``status``."""
    assert check is not None, "the request was let through"
    assert check.status == status
    assert header(check, "Cache-Control") == "no-store"
    assert header(check, "Set-Cookie") is None
    assert TOKEN.encode() not in check.body
    return check


def test_an_api_request_without_the_cookie_is_refused() -> None:
    response = refused(access().check(request("/api/snapshot")), 401)
    assert error_of(response) == UNAUTHENTICATED


@pytest.mark.parametrize("path", ["/api/events", "/api/health", "/api", "/api/turns"])
def test_every_api_path_needs_the_cookie(path: str) -> None:
    method = "POST" if path == "/api/turns" else "GET"
    response = refused(access().check(request(path, method=method)), 401)
    assert error_of(response) == UNAUTHENTICATED


@pytest.mark.parametrize("path", ["/", "/app.js", "/style.css", "/favicon.svg", "/missing.js"])
def test_a_browser_without_the_cookie_sees_the_explanation_not_the_interface(path: str) -> None:
    response = refused(access().check(request(path)), 401)
    assert response.content_type.startswith("text/html")
    assert response.body == PAGE


def test_without_a_page_the_explanation_is_plain_text() -> None:
    bare = WebAccess(TOKEN, host="127.0.0.1", port=PORT)
    response = refused(bare.check(request("/")), 401)
    assert response.content_type.startswith("text/plain")
    assert response.body.decode() == f"{UNAUTHENTICATED}\n"


def test_the_exchange_sets_an_http_only_strict_cookie_and_drops_the_token() -> None:
    response = access().check(request("/", query={"token": [TOKEN]}))

    assert response is not None
    assert response.status == 303
    assert header(response, "Location") == "/"
    assert header(response, "Set-Cookie") == f"{COOKIE}; Path=/; HttpOnly; SameSite=Strict"
    assert header(response, "Cache-Control") == "no-store"
    assert response.body == b""


def test_a_wrong_token_is_refused_and_sets_no_cookie() -> None:
    response = refused(access().check(request("/", query={"token": ["not-the-token"]})), 401)
    assert response.body == PAGE
    assert b"not-the-token" not in response.body


def test_a_wrong_token_is_refused_even_with_a_valid_cookie() -> None:
    """The address is judged on its own: a stale address never passes for a fresh one."""
    refused(access().check(request("/", query={"token": ["stale"]}, cookie=COOKIE)), 401)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/snapshot"), ("GET", "/index.html"), ("POST", "/")],
)
def test_the_token_is_exchanged_only_by_opening_the_root(method: str, path: str) -> None:
    refused(access().check(request(path, method=method, query={"token": [TOKEN]})), 401)


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/"), ("GET", "/app.js"), ("GET", "/api/snapshot"), ("GET", "/api/events"), ("POST", "/api/turns")],
)
def test_the_cookie_lets_every_request_through(method: str, path: str) -> None:
    assert access().check(request(path, method=method, cookie=COOKIE)) is None


@pytest.mark.parametrize(
    "cookie",
    [
        f"super_agent_{PORT}=not-the-token",
        f"super_agent_9999={TOKEN}",
        f"super_agent_{PORT}",
        f"Super_Agent_{PORT}={TOKEN}",
        "",
    ],
)
def test_a_wrong_or_foreign_cookie_is_refused(cookie: str) -> None:
    refused(access().check(request(cookie=cookie)), 401)


def test_other_cookies_on_the_same_host_do_not_hide_this_one() -> None:
    """Cookies are not isolated by port: other services' cookies share the header."""
    header_value = f'theme="dark,blue"; other=1; broken; {COOKIE}; after=2'
    assert access().check(request(cookie=header_value)) is None


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "null",
        f"http://localhost:{PORT}",
        f"https://127.0.0.1:{PORT}",
        "http://127.0.0.1:1",
        f"http://127.0.0.1:{PORT}/",
    ],
)
def test_a_foreign_origin_is_refused_even_with_the_cookie(origin: str) -> None:
    response = refused(access().check(request("/api/turns", method="POST", origin=origin, cookie=COOKIE)), 403)
    assert error_of(response) == "cross-origin request refused"


def test_a_foreign_origin_cannot_exchange_the_token() -> None:
    refused(access().check(request("/", origin="http://evil.example", query={"token": [TOKEN]})), 403)


def test_a_same_origin_request_passes_whatever_the_case() -> None:
    assert access().check(request(method="POST", origin=f"http://127.0.0.1:{PORT}", cookie=COOKIE)) is None
    assert access().check(request(method="POST", origin=f"HTTP://127.0.0.1:{PORT}", cookie=COOKIE)) is None


def test_a_request_without_an_origin_still_needs_the_cookie() -> None:
    refused(access().check(request(method="POST")), 401)
    assert access().check(request(method="POST", cookie=COOKIE)) is None


@pytest.mark.parametrize(
    "host",
    [
        f"attacker.example:{PORT}",
        f"localhost.attacker.example:{PORT}",
        f"127.0.0.1.nip.io:{PORT}",
        f"0.0.0.0:{PORT}",
    ],
)
def test_a_rebinding_host_is_refused_before_the_cookie_or_the_token(host: str) -> None:
    refused(access().check(request(host=host, cookie=COOKIE)), 403)
    refused(access().check(request("/", host=host, query={"token": [TOKEN]})), 403)


@pytest.mark.parametrize("host", ["127.0.0.1:9999", "127.0.0.1", "localhost", f"127.0.0.1:{PORT}0"])
def test_the_host_must_carry_the_bound_port(host: str) -> None:
    refused(access().check(request(host=host, cookie=COOKIE)), 403)


def test_a_request_without_a_host_is_malformed() -> None:
    response = refused(access().check(request(host=None, cookie=COOKIE)), 400)
    assert error_of(response) == "missing Host header"


def test_the_loopback_names_and_the_bind_address_are_the_accepted_hosts() -> None:
    assert access().hosts == {f"{name}:{PORT}" for name in LOOPBACK_HOSTS}
    for host in (f"localhost:{PORT}", f"LOCALHOST:{PORT}", f"[::1]:{PORT}"):
        assert access().check(request(host=host, cookie=COOKIE)) is None


def test_a_non_loopback_bind_still_requires_the_cookie() -> None:
    """Binding another address changes which names are accepted, never whether a cookie is needed."""
    exposed = access("192.0.2.10", bound=("192.0.2.10",))

    assert exposed.address == f"http://192.0.2.10:{PORT}/?token={TOKEN}"
    assert f"192.0.2.10:{PORT}" in exposed.hosts
    response = refused(exposed.check(request(host=f"192.0.2.10:{PORT}")), 401)
    assert error_of(response) == UNAUTHENTICATED
    refused(exposed.check(request("/", host=f"192.0.2.10:{PORT}")), 401)
    assert exposed.check(request(host=f"192.0.2.10:{PORT}", cookie=COOKIE)) is None


def test_a_named_bind_accepts_the_name_and_the_address_it_resolved_to() -> None:
    named = access("Workstation.Example", bound=("192.0.2.20",))
    assert {f"workstation.example:{PORT}", f"192.0.2.20:{PORT}"} <= named.hosts
    assert named.address.startswith(f"http://workstation.example:{PORT}/")


@pytest.mark.parametrize(
    ("host", "printed"),
    [("0.0.0.0", "127.0.0.1"), ("", "127.0.0.1"), ("::", "[::1]")],
)
def test_a_wildcard_bind_is_reached_through_loopback(host: str, printed: str) -> None:
    wildcard = access(host, bound=(host or "0.0.0.0",))

    assert wildcard.address == f"http://{printed}:{PORT}/?token={TOKEN}"
    assert wildcard.hosts == {f"{name}:{PORT}" for name in LOOPBACK_HOSTS}
    refused(wildcard.check(request(host=f"0.0.0.0:{PORT}", cookie=COOKIE)), 403)
    refused(wildcard.check(request(host=f"[::]:{PORT}", cookie=COOKIE)), 403)


def test_ipv6_addresses_are_written_in_brackets() -> None:
    six = access("0:0:0:0:0:0:0:1", bound=("::1",))
    assert six.address == f"http://[::1]:{PORT}/?token={TOKEN}"
    assert six.check(request(host=f"[::1]:{PORT}", cookie=COOKIE)) is None


def test_port_80_also_accepts_a_host_without_a_port() -> None:
    default_port = access(port=80)
    assert default_port.cookie_name == "super_agent_80"
    assert default_port.check(request(host="127.0.0.1", cookie=f"super_agent_80={TOKEN}")) is None
    assert default_port.check(request(host="127.0.0.1:80", cookie=f"super_agent_80={TOKEN}")) is None


def test_each_launch_draws_a_fresh_unguessable_token() -> None:
    tokens = {new_token() for _ in range(16)}
    assert len(tokens) == 16
    for token in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token), token
