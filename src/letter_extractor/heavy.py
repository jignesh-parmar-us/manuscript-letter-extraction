"""Heavy jobs (the full test suite, Measure, Retrain, the harness) without CPU fights (docs/SPEED_PLAN.md, S1).

- **One thread per process:** NumPy (Accelerate) and OpenCV would each use every core; four jobs then make
  32 threads fighting for 8 cores. `limit_threads` (called when the package is imported, before NumPy is)
  sets their thread counts to 1 unless the variables are already set.
- **One heavy job at a time:** `heavy_lock` takes `~/.manuscript-letters-heavy.lock` (process id and what
  runs); a second job says what is running and waits; a lock whose process is gone is taken over.
- **No left-over workers:** `watch_parent` (in every worker process) stops a worker whose parent is gone;
  `stop_orphans` stops workers of this Python left by a run that died, before a heavy job starts.
- **Lower priority:** `lower_priority` (nice) keeps the app and the editor responsive.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List, Optional

THREAD_VARS = ("VECLIB_MAXIMUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
               "OPENCV_FOR_THREADS_NUM")
LOCK = Path.home() / ".manuscript-letters-heavy.lock"
HELD = "MANUSCRIPT_HEAVY_HELD"               # set for the processes a lock holder starts (the test workers)
WAIT = 5.0                                   # seconds between looks at a held lock


def limit_threads() -> None:
    """One thread for NumPy's maths library and OpenCV in this process and the processes it starts. Must run
    before NumPy is imported; a variable already set (by the user) is kept."""
    for v in THREAD_VARS:
        os.environ.setdefault(v, "1")


def one_thread_cv2() -> None:
    """OpenCV's own thread pool to one thread (for a process where cv2 was imported before limit_threads)."""
    import cv2
    cv2.setNumThreads(1)


def lower_priority(n: int = 10) -> None:
    try:
        os.nice(n)
    except OSError:
        pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder(path: Path = LOCK) -> Optional[dict]:
    """What holds the heavy-job lock ({pid, what, started}), or None when it is free or its process is gone."""
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and _alive(int(info.get("pid", 0))) else None


def _try_take(path: Path, what: str) -> Optional[dict]:
    """Take the lock; None when taken, else what holds it."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = lock_holder(path)
            if holder is not None:
                return holder
            try:                                     # its process is gone: take it over
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "what": what, "started": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        return None
    return lock_holder(path) or {"pid": 0, "what": "unknown", "started": ""}


@contextmanager
def heavy_lock(what: str, say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True),
               cancel: Optional[Callable[[], bool]] = None, path: Path = LOCK) -> Iterator[None]:
    """Run one heavy job at a time: wait while another holds the lock (saying once what it is), then hold it.
    `cancel` (the app's jobs) stops the wait: raises InterruptedError. A process started by the holder (its
    pid in MANUSCRIPT_HEAVY_HELD) runs inside the holder's lock."""
    holder = lock_holder(path)
    if holder is not None and str(holder.get("pid")) == os.environ.get(HELD):
        yield
        return
    told = None
    while True:
        holder = _try_take(path, what)
        if holder is None:
            break
        if holder.get("pid") != told:
            say(f"waiting: {holder.get('what')} is running (process {holder.get('pid')}, "
                f"since {holder.get('started')})")
            told = holder.get("pid")
        if cancel and cancel():
            raise InterruptedError("cancelled while waiting for another heavy job")
        time.sleep(WAIT)
    stop_orphans()
    try:
        yield
    finally:
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid() and info.get("what") == what:
                path.unlink()
        except (OSError, ValueError):
            pass


def watch_parent(every: float = 2.0) -> None:
    """In a worker process: stop it when the process that started it is gone (a stopped or crashed run)."""
    parent = os.getppid()

    def loop():
        while True:
            time.sleep(every)
            if os.getppid() != parent:
                os._exit(1)
    threading.Thread(target=loop, name="watch-parent", daemon=True).start()


def worker_init() -> None:
    """For every pool of worker processes: one thread each, lower priority, stopped with their parent."""
    one_thread_cv2()
    lower_priority()
    watch_parent()


def orphans() -> List[tuple]:
    """(pid, command) of worker processes of this Python whose parent is gone (adopted by launchd). On macOS a
    venv's python runs as the framework's Python.app, so the command starts with the base installation."""
    starts = (sys.executable, sys.base_prefix)
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for row in out.splitlines():
        parts = row.split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid, cmd = int(parts[0]), int(parts[1]), parts[2]
        if ppid == 1 and cmd.startswith(starts) and "from multiprocessing." in cmd and pid != os.getpid():
            found.append((pid, cmd))
    return found


def stop_orphans(say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True)) -> int:
    """Stop left-over workers (see `orphans`); how many."""
    found = orphans()
    for pid, _ in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    if found:
        say(f"stopped {len(found)} left-over worker process(es) of an earlier run")
    return len(found)
