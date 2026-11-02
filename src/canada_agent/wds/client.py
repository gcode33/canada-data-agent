"""HTTP client for StatCan WDS: host allowlist, rate limit, retries with jitter, cache.

Every outcome is either parsed JSON or a `WdsError` with a SPEC §8 code, never a raw
exception, so the MCP tools can hand the model a clean `is_error` result.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from canada_agent.errors import ErrorCode
from canada_agent.untrusted import untrusted_text
from canada_agent.wds.cache import Cache, Kind, MemoryCache, cache_key
from canada_agent.wds.limiter import TokenBucket

ALLOWED_HOST = "www150.statcan.gc.ca"
BASE_URL = f"https://{ALLOWED_HOST}/t1/wds/rest/"
BACKOFF_BASE_S = 0.5

log = logging.getLogger(__name__)


class WdsError(Exception):
    def __init__(self, code: ErrorCode, detail: str, untrusted: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.untrusted = untrusted  # upstream text, cleaned; never trusted as instructions


class DisallowedHostError(WdsError):
    """A request (or a redirect) tried to leave the StatCan host. Never retried."""

    def __init__(self, url: httpx.URL) -> None:
        super().__init__(ErrorCode.UPSTREAM_UNAVAILABLE, f"refusing to contact {url.host!r}")


class _Retry(Exception):
    def __init__(
        self, code: ErrorCode, detail: str, body: str = "", retry_after: float = 0.0
    ) -> None:
        self.code, self.detail, self.body, self.retry_after = code, detail, body, retry_after


def _enforce_host(request: httpx.Request) -> None:
    # An event hook runs on every request httpx sends, including each redirect hop.
    url = request.url
    if url.scheme != "https" or url.host != ALLOWED_HOST or url.port not in (None, 443):
        raise DisallowedHostError(url)


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(max(float(response.headers.get("retry-after", 0)), 0.0), 30.0)
    except ValueError:  # the HTTP-date form; fall back to our own backoff
        return 0.0


def _cacheable(body: Any) -> bool:
    """WDS reports many failures inside an HTTP 200 body (FINDINGS-LOG, feat/get-series):
    status FAILED, or SUCCESS with responseStatusCode != 0. Those must never be cached."""
    if not isinstance(body, list):
        return True
    for item in body:
        if isinstance(item, dict) and "status" in item:
            if item["status"] != "SUCCESS":
                return False
            obj = item.get("object")
            if isinstance(obj, dict) and obj.get("responseStatusCode", 0) != 0:
                return False
    return True


class WdsClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        cache: Cache | None = None,
        max_rps: float = 10.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.http = httpx.Client(
            base_url=BASE_URL,
            transport=transport,
            timeout=30.0,
            follow_redirects=True,
            event_hooks={"request": [_enforce_host]},
        )
        self.cache = cache if cache is not None else MemoryCache()
        self.limiter = TokenBucket(max_rps)
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._rng = rng

    def post(self, method: str, body: Any, *, kind: Kind) -> Any:
        return self._call("POST", method, body, kind)

    def get(self, method: str, params: dict[str, str], *, kind: Kind) -> Any:
        return self._call("GET", method, params, kind)

    def _call(self, verb: str, method: str, payload: Any, kind: Kind) -> Any:
        key = cache_key(verb, method, payload)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        last: _Retry | None = None
        for attempt in range(self.max_attempts):
            if attempt:
                backoff = BACKOFF_BASE_S * 2 ** (attempt - 1) * (0.5 + self._rng())
                self._sleep(max(backoff, last.retry_after if last else 0.0))
            self.limiter.acquire()
            try:
                result = self._once(verb, method, payload)
            except _Retry as retry:
                last = retry
                log.warning(
                    "wds retry",
                    extra={
                        "method": method,
                        "attempt": attempt + 1,
                        "code": retry.code,
                        "detail": retry.detail,
                    },
                )
                continue
            if _cacheable(result):
                self.cache.put(key, method, result, kind)
            return result

        assert last is not None
        raise WdsError(
            last.code,
            f"{last.detail} after {self.max_attempts} attempts",
            untrusted_text(last.body),
        )

    def _once(self, verb: str, method: str, payload: Any) -> Any:
        try:
            if verb == "POST":
                response = self.http.post(
                    method,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
            else:
                response = self.http.get(method, params=payload)
        except httpx.RequestError as exc:  # resets, timeouts, DNS, redirect loops, bad encoding
            raise _Retry(ErrorCode.UPSTREAM_UNAVAILABLE, type(exc).__name__) from exc

        status = response.status_code
        if status == 409:
            raise WdsError(
                ErrorCode.UPSTREAM_LOCKED_409,
                "table locked during an update (midnight to 08:30 ET)",
                untrusted_text(response.text),
            )
        if status == 404:
            raise WdsError(
                ErrorCode.NOT_FOUND, f"{method} returned 404", untrusted_text(response.text)
            )
        if status == 429:
            raise _Retry(
                ErrorCode.RATE_LIMITED, "429 from WDS", response.text, _retry_after(response)
            )
        if status >= 500:
            raise _Retry(ErrorCode.UPSTREAM_UNAVAILABLE, f"HTTP {status}", response.text)
        if status >= 400:
            raise WdsError(
                ErrorCode.UPSTREAM_UNAVAILABLE, f"HTTP {status}", untrusted_text(response.text)
            )
        if not response.content.strip():
            raise _Retry(ErrorCode.UPSTREAM_UNAVAILABLE, "empty body")
        try:
            return response.json()
        except ValueError as exc:
            raise _Retry(ErrorCode.UPSTREAM_UNAVAILABLE, "body is not JSON", response.text) from exc
