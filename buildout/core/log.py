"""Structured logging and timing spans.

    from buildout.core.log import log, span
    with span("mind.build", nodes=8592):
        ...
    log("fetched", source="treasury", rows=13)

Human-readable lines on stderr by default; BUILDOUT_LOG=json writes one JSON object per line (for the daily Action's
logs and for grep); BUILDOUT_LOG=quiet silences it. Spans record their durations in TIMINGS for `bench` and the run
manifest.
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

TIMINGS: dict[str, list[float]] = {}


def _mode() -> str:
    return os.environ.get("BUILDOUT_LOG", "text").lower()


def log(event: str, **fields) -> None:
    m = _mode()
    if m == "quiet":
        return
    if m == "json":
        sys.stderr.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event, **fields}, default=str) + "\n")
    else:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        sys.stderr.write(f"[buildout] {event}{(' ' + extra) if extra else ''}\n")


@contextmanager
def span(name: str, **fields):
    t0 = time.perf_counter()
    err = None
    try:
        yield
    except BaseException as exc:
        err = f"{type(exc).__name__}: {exc}"[:200]
        raise
    finally:
        dt = time.perf_counter() - t0
        TIMINGS.setdefault(name, []).append(dt)
        if os.environ.get("BUILDOUT_TRACE"):
            log("span", name=name, seconds=round(dt, 4), **({"error": err} if err else {}), **fields)
