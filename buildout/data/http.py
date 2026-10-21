"""Minimal stdlib HTTP helper (no extra dependencies), with polite retries."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def get(url: str, user_agent: str = "buildout/0.1", retries: int = 3, timeout: int = 30) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url}") from last


def get_json(url: str, user_agent: str = "buildout/0.1") -> dict:
    return json.loads(get(url, user_agent))
