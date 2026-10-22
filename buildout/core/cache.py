"""A content-addressed result cache: the expensive, pure parts of the engine compute once per distinct input and code.

    from buildout.core import cache

    @cache.memo("complexity.build", deps=("buildout.complexity", "buildout.ml"))
    def build(dl, quick=False): ...

A result is keyed by (name, the source code of the listed modules, the call's arguments). Change the code and the key
changes; change the data and the key changes; nothing has to be invalidated by hand. Arguments are hashed through a
canonical encoding (dicts by sorted key, pandas and numpy objects by their bytes), so equal data hashes equally across
runs and processes.

Resilience:
  * entries are written atomically (temporary file, then rename) with a checksum; a truncated or corrupted entry is
    detected on read, deleted and recomputed, never returned
  * the cache is advisory: if the folder cannot be written, the call still returns its result
  * BUILDOUT_NO_CACHE=1 turns it off; BUILDOUT_CACHE=<dir> moves it (default ~/.cache/buildout)
  * prune(max_bytes) drops the least recently used entries

`fetch(name, fn, max_age)` is for network inputs: a fresh copy when the source answers, the last good copy (marked
stale) when it does not.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import io
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable

MAGIC = b"BOC1"
STATS = {"hits": 0, "misses": 0, "errors": 0, "stale": 0}


def root() -> Path:
    return Path(os.environ.get("BUILDOUT_CACHE") or Path.home() / ".cache" / "buildout")


def enabled() -> bool:
    return os.environ.get("BUILDOUT_NO_CACHE", "") not in ("1", "true", "yes")


# ---------------------------------------------------------------- canonical hashing
def _feed(h, o: Any) -> None:
    """Feed a canonical encoding of o into the hash: stable across processes and dict orderings."""
    import numpy as np
    try:
        import pandas as pd
    except ImportError:            # pragma: no cover
        pd = None
    if o is None or isinstance(o, (bool, int, float, str, bytes)):
        h.update(repr((type(o).__name__, o)).encode())
    elif isinstance(o, dict):
        h.update(b"{")
        for k in sorted(o, key=lambda x: repr(x)):
            _feed(h, k)
            _feed(h, o[k])
        h.update(b"}")
    elif isinstance(o, (list, tuple)):
        h.update(b"[" if isinstance(o, list) else b"(")
        for x in o:
            _feed(h, x)
        h.update(b"]")
    elif isinstance(o, (set, frozenset)):
        _feed(h, sorted(o, key=repr))
    elif isinstance(o, np.ndarray):
        h.update(str((o.dtype.str, o.shape)).encode())
        h.update(np.ascontiguousarray(o).tobytes() if o.dtype != object else pickle.dumps(o.tolist()))
    elif isinstance(o, np.generic):
        _feed(h, o.item())
    elif pd is not None and isinstance(o, (pd.DataFrame, pd.Series)):
        h.update(type(o).__name__.encode())
        h.update(pd.util.hash_pandas_object(o, index=True).values.tobytes())
        if isinstance(o, pd.DataFrame):
            _feed(h, [str(c) for c in o.columns])
            _feed(h, [str(t) for t in o.dtypes])
    elif pd is not None and isinstance(o, pd.Timestamp):
        _feed(h, o.isoformat())
    elif isinstance(o, Path):
        _feed(h, str(o))
    else:
        h.update(pickle.dumps(o, protocol=4))


def digest(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        _feed(h, p)
    return h.hexdigest()


@functools.lru_cache(maxsize=256)
def code_hash(module: str) -> str:
    """The source of a module (and the version of the package), so a code change invalidates its results."""
    from buildout import __version__
    m = importlib.import_module(module)
    f = getattr(m, "__file__", None)
    src = Path(f).read_bytes() if f else module.encode()
    return hashlib.sha256(src + __version__.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- storage
def _path(key: str) -> Path:
    return root() / key[:2] / f"{key}.pkl"


def get(key: str) -> tuple[bool, Any]:
    p = _path(key)
    if not enabled() or not p.exists():
        return False, None
    try:
        blob = p.read_bytes()
        if blob[:4] != MAGIC or hashlib.sha256(blob[36:]).digest() != blob[4:36]:
            raise ValueError("bad checksum")
        val = pickle.loads(blob[36:])
        os.utime(p)                                   # touched: least recently used is pruned first
        return True, val
    except Exception:                                 # corrupted or unreadable: drop it and recompute
        STATS["errors"] += 1
        try:
            p.unlink()
        except OSError:
            pass
        return False, None


def put(key: str, val: Any) -> bool:
    if not enabled():
        return False
    p = _path(key)
    try:
        body = pickle.dumps(val, protocol=pickle.HIGHEST_PROTOCOL)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(MAGIC + hashlib.sha256(body).digest() + body)
        os.replace(tmp, p)
        return True
    except Exception:                                 # a read-only or full disk never breaks the computation
        STATS["errors"] += 1
        return False


def memo(name: str, deps: tuple[str, ...] = (), ignore: tuple[str, ...] = (), require: tuple[str, ...] = ()) -> Callable:
    """Cache a pure function's result by its code and arguments. `deps` lists the modules whose source it depends on
    (its own module is always included); `ignore` names keyword arguments that do not change the result; `require`
    names arguments that must be given (not None) for the call to be cacheable: a function that would fetch its own
    data when an argument is missing is not pure, so that call runs uncached."""
    def wrap(fn: Callable) -> Callable:
        import inspect
        mods = tuple(dict.fromkeys((fn.__module__, *deps)))
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if not enabled():
                return fn(*args, **kwargs)
            if require:
                b = sig.bind_partial(*args, **kwargs)
                if any(b.arguments.get(r) is None for r in require):
                    return fn(*args, **kwargs)
            kw = {k: v for k, v in kwargs.items() if k not in ignore}
            key = digest(name, [code_hash(m) for m in mods], args, kw)
            hit, val = get(key)
            if hit:
                STATS["hits"] += 1
                return val
            STATS["misses"] += 1
            val = fn(*args, **kwargs)
            put(key, val)
            return val

        inner.uncached = fn                          # type: ignore[attr-defined]
        return inner
    return wrap


def fetch(name: str, fn: Callable[[], Any], max_age: float = 86400.0, ok: Callable[[Any], bool] = lambda v: v is not None) -> tuple[Any, dict]:
    """A network input with a fallback: a copy younger than max_age seconds is reused; otherwise fn() is called and, if
    it fails or returns something `ok` rejects, the last good copy is returned and marked stale."""
    key = digest("fetch", name)
    p = _path(key)
    age = time.time() - p.stat().st_mtime if p.exists() else None
    if age is not None and age < max_age:
        hit, val = get(key)
        if hit:
            STATS["hits"] += 1
            return val, {"source": "cache", "age_s": round(age), "stale": False}
    try:
        val = fn()
        if not ok(val):
            raise ValueError("the fresh copy failed its check")
        put(key, val)
        return val, {"source": "live", "age_s": 0, "stale": False}
    except Exception as exc:
        hit, val = get(key)
        if hit:
            STATS["stale"] += 1
            return val, {"source": "last good", "age_s": round(age or 0), "stale": True, "error": f"{type(exc).__name__}: {exc}"[:200]}
        raise


def prune(max_bytes: int = 2 << 30) -> dict:
    """Keep the cache under max_bytes by dropping least recently used entries first."""
    files = sorted((p for p in root().glob("*/*.pkl")), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for p in files:
        if total <= max_bytes:
            break
        total -= p.stat().st_size
        p.unlink(missing_ok=True)
        removed += 1
    return {"entries": len(files) - removed, "bytes": total, "removed": removed}


def info() -> dict:
    files = list(root().glob("*/*.pkl")) if root().exists() else []
    return {"dir": str(root()), "enabled": enabled(), "entries": len(files), "bytes": sum(p.stat().st_size for p in files), **STATS}


def clear() -> int:
    n = 0
    for p in root().glob("*/*.pkl"):
        p.unlink(missing_ok=True)
        n += 1
    return n


def _selftest() -> bool:                                # used by `doctor`
    buf = io.BytesIO(pickle.dumps({"a": 1}))
    return pickle.load(buf) == {"a": 1}
