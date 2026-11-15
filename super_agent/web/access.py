"""Who may use the web interface: the launch token, its cookie, and where a request came from.

The interface can run tools, so reaching it is the same as being allowed to run
them. A loopback bind does not keep out another local process, a page that
rebinds its hostname to 127.0.0.1, or a cross-site request, so every request
passes :meth:`WebAccess.check` before it is routed:

* it must name this server by a host the server answers to, which defeats DNS
  rebinding;
* a browser must not have sent it from another origin, which defeats cross-site
  requests;
* it must carry the cookie a browser receives in exchange for the launch token,
  which only someone who read the startup line can have obtained.

The checks are a pure function of a request, so they are tested without a
socket. The protocol is ``docs/spec/application-interface.md#web-访问认证``.
"""

from __future__ import annotations

import dataclasses
import hmac
import ipaddress
import secrets
from collections.abc import Iterable
from typing import Final

from super_agent.web.routes import Request, Response, error_response

__all__ = [
    "COOKIE_PREFIX",
    "LOOPBACK_HOSTS",
    "TOKEN_PARAMETER",
    "UNAUTHENTICATED",
    "WebAccess",
    "display_host",
    "new_token",
    "url_host",
]

#: Random bytes in a launch token: far beyond guessing, short enough to paste.
TOKEN_BYTES: Final[int] = 32

#: The query parameter the startup address carries the token in.
TOKEN_PARAMETER: Final[str] = "token"

#: The cookie's name is this plus the bound port. Browsers do not isolate cookies
#: by port, so two interfaces on one host must not overwrite each other's cookie.
COOKIE_PREFIX: Final[str] = "super_agent_"

#: Host names every interface answers to, whatever address it is bound to.
LOOPBACK_HOSTS: Final[tuple[str, ...]] = ("127.0.0.1", "localhost", "[::1]")

#: What a request without the cookie is told: the remedy, never the token.
UNAUTHENTICATED: Final[str] = "authentication required: open the address printed at startup"

#: An access answer belongs to one request of one launch; nothing may keep it.
_NO_STORE: Final[tuple[str, str]] = ("Cache-Control", "no-store")


def new_token() -> str:
    """A fresh launch token from the operating system's secure random source."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def url_host(host: str) -> str:
    """``host`` the way a URL and a Host header spell it: lower case, IPv6 in brackets."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower()
    return f"[{address.compressed}]" if address.version == 6 else address.compressed


def display_host(host: str) -> str:
    """The host the startup address names: the bind address, or loopback for a wildcard.

    No browser can open "every address", so a wildcard bind is reached through
    the loopback address of the same family.
    """
    if not _is_wildcard(host):
        return url_host(host)
    return "[::1]" if ":" in host else "127.0.0.1"


def _is_wildcard(host: str) -> bool:
    """Whether ``host`` means every address, which is never a name a request can carry."""
    if not host:
        return True
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def _refusal(status: int, message: str) -> Response:
    return dataclasses.replace(error_response(status, message), headers=(_NO_STORE,))


class WebAccess:
    """The access rules of one running interface: its token, the names it answers to, its port."""

    __slots__ = ("_cookie_name", "_display_host", "_hosts", "_page", "_port", "_secret", "_token")

    def __init__(
        self,
        token: str,
        *,
        host: str,
        port: int,
        bound: Iterable[str] = (),
        page: bytes | None = None,
    ) -> None:
        """``bound`` is what the listening sockets actually got; ``page`` is what a browser without the cookie sees."""
        self._token = token
        self._secret = token.encode("utf-8")
        self._port = port
        self._display_host = display_host(host)
        self._cookie_name = f"{COOKIE_PREFIX}{port}"
        self._page = page
        names: set[str] = set(LOOPBACK_HOSTS)
        names.update(url_host(name) for name in (host, *bound) if not _is_wildcard(name))
        # A browser leaves the port out of the Host header only when it is the
        # scheme's default, so only port 80 accepts a bare name.
        hosts = {f"{name}:{port}" for name in names}
        if port == 80:
            hosts.update(names)
        self._hosts = frozenset(hosts)

    @property
    def address(self) -> str:
        """The address to open in a browser. It carries the token, so it is printed once."""
        return f"http://{self._display_host}:{self._port}/?{TOKEN_PARAMETER}={self._token}"

    @property
    def cookie_name(self) -> str:
        """The name of the cookie the exchange sets, which carries the bound port."""
        return self._cookie_name

    @property
    def hosts(self) -> frozenset[str]:
        """Every Host header value this interface accepts, lower case."""
        return self._hosts

    def check(self, request: Request) -> Response | None:
        """The answer for a request that may not go further, or ``None`` when it may.

        The order is the protocol's: the host first, because nothing else in a
        rebound request can be trusted; the origin next; then the token exchange,
        which is how a browser gets its cookie; and the cookie last.
        """
        host = request.headers.get("host", "").lower()
        if not host:
            return _refusal(400, "missing Host header")
        if host not in self._hosts:
            return _refusal(403, "host not allowed")
        origin = request.headers.get("origin")
        if origin is not None and origin.lower() != f"http://{host}":
            return _refusal(403, "cross-origin request refused")
        if request.method == "GET" and request.path == "/":
            # The query parser drops an empty value, so an empty token is no token.
            candidates = request.query.get(TOKEN_PARAMETER)
            if candidates:
                return self._exchange(candidates[0])
        if self._has_cookie(request.headers.get("cookie", "")):
            return None
        if request.path == "/api" or request.path.startswith("/api/"):
            return _refusal(401, UNAUTHENTICATED)
        return self._explanation()

    def _exchange(self, candidate: str) -> Response:
        """Trade a correct token for the cookie, and send the browser to the bare address.

        The redirect is what takes the token out of the address bar: the page a
        user keeps open, bookmarks or shares never carries it.
        """
        if not self._matches(candidate):
            return self._explanation()
        cookie = f"{self._cookie_name}={self._token}; Path=/; HttpOnly; SameSite=Strict"
        return Response(
            status=303,
            content_type="",
            headers=(("Location", "/"), ("Set-Cookie", cookie), _NO_STORE),
        )

    def _explanation(self) -> Response:
        """What a browser without the cookie sees instead of an interface that cannot work."""
        if self._page is None:
            return Response(
                status=401,
                body=f"{UNAUTHENTICATED}\n".encode(),
                content_type="text/plain; charset=utf-8",
                headers=(_NO_STORE,),
            )
        return Response(status=401, body=self._page, content_type="text/html; charset=utf-8", headers=(_NO_STORE,))

    def _has_cookie(self, header: str) -> bool:
        """Whether the Cookie header holds this launch's cookie.

        Cookies of every other service on the same host arrive in the same
        header, since cookies are not isolated by port. The header is split by
        hand so that a value some other service chose cannot hide this one.
        """
        for pair in header.split(";"):
            name, separator, value = pair.strip().partition("=")
            if separator and name == self._cookie_name and self._matches(value):
                return True
        return False

    def _matches(self, candidate: str) -> bool:
        """A constant-time comparison with the token, on bytes so any text compares."""
        return hmac.compare_digest(candidate.encode("utf-8", "replace"), self._secret)
