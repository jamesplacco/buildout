"""The engine runner: a dependency graph of tasks, run in parallel, each isolated, timed out, retried and checked.

    tasks = [Task("valuation", fn, reads=["capex.json"], writes=["valuation.json"]), ...]
    manifest = run(tasks, out_dir, jobs=4)

What it guarantees:
  order       a task starts only after every task that writes a file it reads has finished (the graph comes from
              reads and writes; a cycle is an error raised before anything runs)
  isolation   each task runs in its own process (forkserver), so a crash, a hang or a memory blow-up in one engine never
              takes down the run or another engine; `isolate=False` runs in-process for debugging and tests
  timeouts    a task over its time limit is terminated, then killed
  retries     a task that raises is retried with exponential backoff (for engines that touch the network)
  contracts   every file a task writes is checked against its contract (core.contracts); a file that breaks it is
              rejected
  last good   before a task runs, its current outputs are copied aside; if the task fails, times out or writes a
              rejected file, the previous files are restored, so the page shows yesterday's numbers, marked, never
              a broken file
  provenance  the manifest records, per task, its status, attempts, time, the content hashes of what it read and
              wrote, its error and the tasks whose failure left it reading last-good inputs

Statuses: ok, failed, timeout, rejected (contract), skipped, external. `kept_last_good` says the previous outputs
were restored.
"""
from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import pickle
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import contracts


@dataclass
class Task:
    name: str
    fn: Callable[[Path], None] | None
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    timeout: float = 900.0
    retries: int = 0
    backoff: float = 1.0
    meta: dict = field(default_factory=dict)


PRELOAD = ("numpy", "pandas", "buildout.engine", "buildout.mind", "buildout.reasoner", "buildout.ooda", "buildout.hedgebook")


class CycleError(ValueError):
    pass


def _hash(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def graph(tasks: list[Task]) -> dict[str, set[str]]:
    """name -> the names of tasks it must wait for (those writing a file it reads)."""
    writer: dict[str, str] = {}
    for t in tasks:
        for w in t.writes:
            writer.setdefault(w, t.name)
    deps = {t.name: {writer[r] for r in t.reads if r in writer and writer[r] != t.name} for t in tasks}
    # cycle check (Kahn)
    indeg = {n: len(d) for n, d in deps.items()}
    users: dict[str, list[str]] = {n: [] for n in deps}
    for n, d in deps.items():
        for x in d:
            users[x].append(n)
    ready = [n for n, k in indeg.items() if k == 0]
    seen = 0
    while ready:
        n = ready.pop()
        seen += 1
        for u in users[n]:
            indeg[u] -= 1
            if indeg[u] == 0:
                ready.append(u)
    if seen != len(deps):
        raise CycleError("the engines read each other's files in a cycle: " + ", ".join(sorted(n for n, k in indeg.items() if k > 0)))
    return deps


def levels(tasks: list[Task]) -> list[list[str]]:
    deps = graph(tasks)
    done: set[str] = set()
    out = []
    while len(done) < len(deps):
        lvl = sorted(n for n, d in deps.items() if n not in done and d <= done)
        out.append(lvl)
        done |= set(lvl)
    return out


def _child(fn: Callable, out: str, conn) -> None:            # runs in the forked process
    try:
        fn(Path(out))
        conn.send(("ok", None, None))
    except BaseException as exc:                              # noqa: BLE001 - report everything to the parent
        conn.send(("failed", f"{type(exc).__name__}: {exc}"[:300], traceback.format_exc()[-1500:]))
    finally:
        conn.close()


Result = tuple[str, Optional[str], Optional[str]]          # (status, error, traceback)


class _Running:
    def __init__(self, task: Task, out: Path, isolate: bool, ctx: Any):
        assert task.fn is not None
        self.task, self.t0 = task, time.perf_counter()
        self.result: Result | None = None
        self.proc: Any = None
        if isolate and ctx is not None:
            try:
                pickle.dumps(task.fn)                         # a lambda or a local function cannot cross into a process
            except Exception:
                isolate = False
        if not isolate or ctx is None:
            try:
                task.fn(out)
                self.result = ("ok", None, None)
            except Exception as exc:
                self.result = ("failed", f"{type(exc).__name__}: {exc}"[:300], traceback.format_exc()[-1500:])
            return
        self.recv, send = ctx.Pipe(duplex=False)
        self.proc = ctx.Process(target=_child, args=(task.fn, str(out), send), daemon=True)
        self.proc.start()
        send.close()

    def poll(self) -> Result | None:
        if self.result is not None or self.proc is None:
            return self.result
        if self.recv.poll():
            try:
                self.result = self.recv.recv()
            except EOFError:                                   # the pipe closed with nothing in it: the process died
                self.proc.join(2)
                self.result = ("failed", f"the engine process died (exit code {self.proc.exitcode})", None)
        elif not self.proc.is_alive():
            self.proc.join()
            self.result = ("failed", f"the engine process died (exit code {self.proc.exitcode})", None)
        elif time.perf_counter() - self.t0 > self.task.timeout:
            self.proc.terminate()
            self.proc.join(3)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(1)
            self.result = ("timeout", f"over the {self.task.timeout:g}s limit", None)
        if self.result is not None and self.proc is not None:
            self.proc.join(1)
        return self.result


def _backup(out: Path, task: Task) -> Path:
    b = out / ".lastgood" / task.name
    if b.exists():
        shutil.rmtree(b, ignore_errors=True)
    b.mkdir(parents=True, exist_ok=True)
    for w in task.writes:
        if (out / w).exists():
            shutil.copy2(out / w, b / w)
    return b


def _restore(out: Path, task: Task, b: Path) -> bool:
    restored = False
    for w in task.writes:
        if (b / w).exists():
            os.replace(b / w, out / w)
            restored = True
    return restored


def run(tasks: list[Task], out_dir, jobs: int | None = None, isolate: bool = True, on_event: Callable[[str, dict], None] | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deps = graph(tasks)
    by = {t.name: t for t in tasks}
    jobs = max(1, jobs or min(8, os.cpu_count() or 2))
    ctx = None
    if isolate:
        # forkserver: each engine starts from a clean, single-threaded server process (fork from a process that
        # already runs numpy's thread pools can deadlock); BUILDOUT_MP=fork or spawn overrides
        for method in ([os.environ["BUILDOUT_MP"]] if os.environ.get("BUILDOUT_MP") else []) + ["forkserver", "spawn"]:
            try:
                ctx = mp.get_context(method)
                if method == "forkserver":                     # the server imports the heavy libraries once
                    ctx.set_forkserver_preload(list(PRELOAD))
                break
            except ValueError:
                continue
    rows: dict[str, dict] = {}
    pending = [t.name for t in tasks if t.fn is not None]
    for t in tasks:
        if t.fn is None:
            rows[t.name] = {"status": "external", "outputs": {w: _hash(out / w) for w in t.writes}}
    finished: set[str] = set(rows)
    running: dict[str, _Running] = {}
    attempts: dict[str, int] = {}
    backups: dict[str, Path] = {}
    wait_until: dict[str, float] = {}
    emit = on_event or (lambda kind, info: None)
    t_start = time.perf_counter()

    def start(name: str) -> None:
        t = by[name]
        if name not in backups:
            backups[name] = _backup(out, t)
            rows[name] = {"inputs": {r: _hash(out / r) for r in t.reads if r != "*"},
                          "stale_inputs": sorted(d for d in deps[name] if rows.get(d, {}).get("status") not in ("ok", "external", None))}
        attempts[name] = attempts.get(name, 0) + 1
        emit("start", {"task": name, "attempt": attempts[name]})
        running[name] = _Running(t, out, isolate, ctx)

    def finish(name: str, res: tuple, seconds: float) -> None:
        t = by[name]
        status, err, trace = res
        problems: list[str] = []
        if status == "ok":
            for w in t.writes:
                if w.endswith(".json"):
                    problems += contracts.check(out / w)
            if problems:
                status = "rejected"
        row = rows[name]
        row.update({"status": status, "attempts": attempts[name], "seconds": round(row.get("seconds", 0) + seconds, 3)})
        if err:
            row["error"] = err
        if trace:
            row["trace"] = trace
        if problems:
            row["contract"] = problems[:8]
        if status != "ok":
            row["kept_last_good"] = _restore(out, t, backups[name])
        row["outputs"] = {w: _hash(out / w) for w in t.writes}
        shutil.rmtree(backups[name], ignore_errors=True)
        finished.add(name)
        emit("finish", {"task": name, **{k: row[k] for k in ("status", "seconds", "attempts")}})

    while pending or running:
        now = time.perf_counter()
        for name in list(pending):
            if len(running) >= jobs:
                break
            if deps[name] <= finished and wait_until.get(name, 0) <= now:
                pending.remove(name)
                start(name)
        for name, r in list(running.items()):
            res = r.poll()
            if res is None:
                continue
            del running[name]
            secs = time.perf_counter() - r.t0
            if res[0] == "failed" and attempts[name] <= by[name].retries:
                rows[name]["seconds"] = round(rows[name].get("seconds", 0) + secs, 3)
                rows[name].setdefault("errors", []).append(res[1])
                wait_until[name] = time.perf_counter() + by[name].backoff * 2 ** (attempts[name] - 1)
                pending.append(name)
                emit("retry", {"task": name, "attempt": attempts[name], "error": res[1]})
                continue
            finish(name, res, secs)
        if running or pending:
            time.sleep(0.005)
    wall = time.perf_counter() - t_start
    serial = sum(r.get("seconds", 0) for r in rows.values())
    order = [n for lvl in levels(tasks) for n in lvl]
    return {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs, "isolated": bool(isolate and ctx),
            "wall_seconds": round(wall, 3), "serial_seconds": round(serial, 3), "speedup": round(serial / wall, 2) if wall > 0 else None,
            "levels": levels(tasks), "tasks": {n: rows[n] for n in order if n in rows},
            "counts": {s: sum(1 for r in rows.values() if r.get("status") == s) for s in ("ok", "failed", "timeout", "rejected", "external")}}
