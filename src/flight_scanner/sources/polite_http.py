"""Polite HTTP for the unofficial airline calendar adapters (Ryanair, Wizz).

`PoliteHttp.request(method, url, ...)` sends one request at a low, evenly spaced rate and:
  - retries 429, 5xx and network errors with exponential backoff (honouring Retry-After) up to
    `max_retries` times, then raises `SourceUnavailable`;
  - raises `SourceBlocked` at once, without retrying, when the site turns us away: 401/403/407/
    409/451, or a challenge page (HTML, captcha or bot-protection markers) where JSON was
    expected. Nothing is ever done to get past such a block: no proxy rotation, no browser
    impersonation, no CAPTCHA solving;
  - returns every other answer (200, and 400/404 "no such route") to the adapter.
The transport, sleep and monotonic clock are injectable so tests never touch the network.
"""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from flight_scanner.sources.base import SourceBlocked, SourceUnavailable


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        return {k.lower(): v for k, v in self.headers.items()}.get(name.lower())


# (method, url, headers, body, timeout) -> response; network failures raise OSError
Transport = Callable[[str, str, dict[str, str], bytes | None, float], HttpResponse]

BLOCKED_STATUSES = {401, 403, 407, 409, 451}
_CHALLENGE_MARKERS = (b"captcha", b"verify you are human", b"are you a robot", b"kpsdk")
_CHALLENGE_HEADERS = ("x-kpsdk-ct", "x-kpsdk-r", "cf-mitigated")


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> HttpResponse:
    """The real HTTP call (stdlib only), gunzipping the body."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, resp_headers, data = resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        status, resp_headers, data = e.code, dict(e.headers or {}), e.read() or b""
    if {k.lower(): v for k, v in resp_headers.items()}.get("content-encoding") == "gzip":
        data = gzip.decompress(data)
    return HttpResponse(status, resp_headers, data)


def is_blocked(resp: HttpResponse) -> bool:
    """Access denied, or a bot-protection challenge instead of the JSON the endpoint returns.
    Body sniffing only applies to 200 answers: a 5xx HTML error page is an outage, not a block."""
    if resp.status in BLOCKED_STATUSES or any(resp.header(h) for h in _CHALLENGE_HEADERS):
        return True
    if resp.status != 200:
        return False
    head = resp.body[:4096].lower()
    if "html" in (resp.header("content-type") or "") or head.lstrip().startswith(b"<"):
        return True
    return any(m in head for m in _CHALLENGE_MARKERS)


class PoliteHttp:
    def __init__(
        self,
        source: str,
        *,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        requests_per_minute: float = 6,
        max_retries: int = 2,
        backoff_base_s: float = 10.0,
        backoff_max_s: float = 120.0,
        timeout_s: float = 30.0,
    ):
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.source = source
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._interval = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._backoff_max = backoff_max_s
        self._timeout = timeout_s
        self._last_request_at: float | None = None

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip", **(headers or {})}
        attempt = 0
        while True:
            self._wait_for_slot()
            try:
                resp = self._transport(method, url, headers, body, self._timeout)
                problem = None
            except OSError as e:
                resp, problem = None, f"{type(e).__name__}: {e}"
            if resp is not None:
                if is_blocked(resp):
                    raise SourceBlocked(f"{self.source}: turned away (HTTP {resp.status})")
                if resp.status == 429 or resp.status >= 500:
                    problem = f"HTTP {resp.status}"
            if problem is None:
                return resp
            if attempt >= self._max_retries:
                raise SourceUnavailable(f"{self.source}: {problem} after {attempt + 1} attempt(s)")
            self._sleep(self._backoff(attempt, resp))
            attempt += 1

    def _wait_for_slot(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            wait = self._last_request_at + self._interval - now
            if wait > 0:
                self._sleep(wait)
                now = self._monotonic()
        self._last_request_at = now

    def _backoff(self, attempt: int, resp: HttpResponse | None) -> float:
        retry_after = resp.header("retry-after") if resp is not None else None
        if retry_after is not None:
            try:
                return min(float(retry_after), self._backoff_max)
            except ValueError:
                pass
        return min(self._backoff_base * 2**attempt, self._backoff_max)
