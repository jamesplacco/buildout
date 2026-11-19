"""Minimal stdlib HTTP helper (no extra dependencies), with polite retries."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


# v0.33: a per-host circuit breaker. A site that is down or refuses this machine used to cost about 100 seconds a file
# (three tries at a 30-second timeout); fifty series from one blocked site ran a daily job past its time limit. After
# BREAKER consecutive files fail on one host, the rest of the process skips that host at once; any success resets it.
BREAKER = 2
_fails: dict[str, int] = {}


def host_down(url: str) -> bool:
    return _fails.get(urllib.parse.urlsplit(url).netloc, 0) >= BREAKER


def reset() -> None:
    _fails.clear()


def get(url: str, user_agent: str = "buildout/0.1", retries: int = 3, timeout: int = 30) -> bytes:
    host = urllib.parse.urlsplit(url).netloc
    user_agent = " ".join(str(user_agent).split())      # v0.39.1: a pasted line break or tab in a contact header is a space, not an invalid header
    if _fails.get(host, 0) >= BREAKER:
        raise RuntimeError(f"skipped: {host} failed {_fails[host]} files in a row this run: {url}")
    last: Exception | None = None
    tries = 0
    for attempt in range(retries):
        tries += 1
        try:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
            except ValueError:
                raise RuntimeError("the User-Agent header is not valid (its value is not repeated here)") from None
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            _fails[host] = 0
            return body
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (404, 410):                       # a missing file: the host is up, so the breaker resets
                _fails[host] = 0
                raise RuntimeError(f"GET failed (HTTP {exc.code}, not found): {url}") from exc
            if exc.code in (400, 401, 403):                  # a refusal: retrying will not help
                break
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    _fails[host] = _fails.get(host, 0) + 1
    code = f" (HTTP {last.code})" if isinstance(last, urllib.error.HTTPError) else ""
    raise RuntimeError(f"GET failed{code} after {tries} tries: {url}") from last


def get_json(url: str, user_agent: str = "buildout/0.1") -> dict:
    return json.loads(get(url, user_agent))


# v0.47: retries for vendor SDK calls (Databento's client raises its own errors and retries nothing). A gateway timeout
# is the vendor's bad minute, not a reason to lose the day's run or to fall back to another source without saying so.
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_TRANSIENT_NAMES = ("ServerError", "Timeout", "ConnectionError", "ConnectionReset", "ChunkedEncoding", "RemoteDisconnected", "IncompleteRead")


def is_transient(exc: BaseException) -> bool:
    """Is this the kind of failure a second try can fix: a 5xx or 429 from the server, a timeout, a dropped connection?
    A refusal (401, 403, 422: a missing licence, a bad request) is not."""
    code = getattr(exc, "http_status", None) or getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int):
        return code in TRANSIENT_STATUS
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return any(n in type(exc).__name__ for n in _TRANSIENT_NAMES)


def with_retries(fn, tries: int = 3, backoff: float = 2.0, sleep=time.sleep, on_retry=None):
    """Call fn(); on a transient failure wait backoff, 2 x backoff, ... and call again, `tries` times in all. Anything
    else, and the last transient failure, is raised unchanged. `on_retry(attempt, exc)` is told about each retry."""
    for attempt in range(1, max(1, tries) + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below unless it is transient and tries remain
            if attempt >= tries or not is_transient(exc):
                raise
            if on_retry is not None:
                on_retry(attempt, exc)
            sleep(backoff * 2 ** (attempt - 1))
