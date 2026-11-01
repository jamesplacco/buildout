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
    if _fails.get(host, 0) >= BREAKER:
        raise RuntimeError(f"skipped: {host} failed {_fails[host]} files in a row this run: {url}")
    last: Exception | None = None
    tries = 0
    for attempt in range(retries):
        tries += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
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
