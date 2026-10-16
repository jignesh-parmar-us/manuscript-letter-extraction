"""The backend tests in 4 processes at once (docs/SPEED_PLAN.md, S2). No new package: unittest and multiprocessing.

Usage: PYTHONPATH=src .venv/bin/python tools/test_parallel.py [fast|full] [-j 4] [test_module ...]

- `fast` (the default): all tests but the sample-page and end-to-end ones (classes with LEVEL "samples" or
  "full"): while implementing and before a commit.
- `full`: all of them, the same tests as `unittest discover -s tests`: at the end of a plan or before a merge.
  A heavy job: it takes the heavy-job lock (letter_extractor.heavy) and waits for another one to finish.

Each process has one thread and a lower priority, and stops when this run is stopped. The test modules
start class by class, slowest first (their times of the last run are kept in tests/.durations.json); the sample-page
tests run together in one process, so each sample page is cut once (tests/samplepages.py). Prints a line
per slow (10 s or more) or failed class, then one summary: tests passed, failed, the failures, the slowest tests.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import multiprocessing
import os
import sys
import time
import unittest
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
DURATIONS = TESTS / ".durations.json"
SAMPLES_TASK = "sample pages"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TESTS))

from letter_extractor import heavy                                  # noqa: E402  (one thread, before NumPy)


def _flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flatten(t)
        else:
            yield t


def _level(test) -> str:
    return getattr(type(test), "LEVEL", "fast")


def _classes(module: str):
    """The top-level classes of a test module, read without importing it."""
    tree = ast.parse((TESTS / f"{module}.py").read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]


def _tests(task: str, level: str, modules):
    """The tests of one task ("module.Class"): its tests of the level; SAMPLES_TASK: every sample-page test."""
    loader = unittest.TestLoader()
    if task == SAMPLES_TASK:
        return [t for m in modules for t in _flatten(loader.loadTestsFromName(m)) if _level(t) == "samples"]
    module, name = task.rsplit(".", 1)
    cls = getattr(importlib.import_module(module), name)
    if not (isinstance(cls, type) and issubclass(cls, unittest.TestCase)):
        return []
    keep = {"fast": ("fast",), "full": ("fast", "full")}[level]
    return [t for t in _flatten(loader.loadTestsFromTestCase(cls)) if _level(t) in keep]


class _Result(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.times = []

    def addDuration(self, test, elapsed):                           # Python 3.12+
        self.times.append((test.id(), elapsed))


def _run(args):
    """In a worker: run one task; its counts, failures and times (plain data, pickled back)."""
    task, level, modules = args
    t0 = time.time()
    out = io.StringIO()
    try:
        suite = unittest.TestSuite(_tests(task, level, modules))
    except Exception as e:                                           # a module that does not import
        import traceback
        return {"task": task, "seconds": time.time() - t0, "run": 1, "failures": [],
                "errors": [(task, "".join(traceback.format_exception(e)))], "skipped": 0, "times": []}
    runner = unittest.TextTestRunner(stream=out, verbosity=0, buffer=True, resultclass=_Result)
    r = runner.run(suite)
    return {"task": task, "seconds": time.time() - t0, "run": r.testsRun,
            "failures": [(t.id(), tb) for t, tb in r.failures + [(x, "unexpected success") for x in r.unexpectedSuccesses]],
            "errors": [(t.id() if hasattr(t, "id") else str(t), tb) for t, tb in r.errors],
            "skipped": len(r.skipped), "times": r.times}


def _init():
    os.chdir(ROOT)
    os.environ.setdefault("LETTER_EXTRACTOR_WORKERS", "1")          # pages cut in the test process itself
    heavy.worker_init()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("level", nargs="?", default="fast", choices=("fast", "full"))
    ap.add_argument("modules", nargs="*", help="test modules (default: every tests/test_*.py)")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    a = ap.parse_args()
    modules = a.modules or sorted(p.stem for p in TESTS.glob("test_*.py"))
    modules = [m[:-3] if m.endswith(".py") else m.split("/")[-1].replace("tests.", "") for m in modules]
    if a.level == "full":
        heavy.lower_priority()
        with heavy.heavy_lock("full tests (tools/test_parallel.py)"):
            os.environ[heavy.HELD] = str(os.getpid())                 # the test workers run inside this lock
            return _main(a, modules)
    return _main(a, modules)


def _main(a, modules) -> int:
    try:
        known = json.loads(DURATIONS.read_text())
    except (OSError, ValueError):
        known = {}
    tasks = [f"{m}.{c}" for m in modules for c in _classes(m)] + ([SAMPLES_TASK] if a.level == "full" else [])
    tasks.sort(key=lambda t: -known.get(t, 1e9))                        # slowest first; new ones first of all
    t0 = time.time()
    ctx = multiprocessing.get_context("spawn")
    results = []
    print(f"{a.level}: {len(modules)} test modules ({len(tasks)} classes) in {a.jobs} processes", flush=True)
    # not multiprocessing.Pool: its workers are daemons and may not start the page workers that capture uses
    ex = ProcessPoolExecutor(min(a.jobs, len(tasks)), mp_context=ctx, initializer=_init)
    try:
        futs = [ex.submit(_run, (t, a.level, modules)) for t in tasks]
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            bad = len(r["failures"]) + len(r["errors"])
            if bad or r["seconds"] >= 10:
                    print(f"{r['seconds']:6.1f} s  {r['task']:<48} {r['run']:4d} tests"
                      f"{'  FAILED ' + str(bad) if bad else ''}", flush=True)
    except KeyboardInterrupt:
        for p in list(getattr(ex, "_processes", {}).values()):
            p.terminate()
        ex.shutdown(wait=False, cancel_futures=True)
        print("stopped", flush=True)
        return 130
    ex.shutdown()
    wall = time.time() - t0
    run = sum(r["run"] for r in results)
    failures = [f for r in results for f in r["failures"]]
    errors = [e for r in results for e in r["errors"]]
    for name, tb in failures + errors:
        print(f"\n{'=' * 70}\n{name}\n{'-' * 70}\n{tb}", flush=True)
    times = sorted((x for r in results for x in r["times"]), key=lambda x: -x[1])[:10]
    print("\nslowest tests:")
    for name, s in times:
        print(f"  {s:6.1f} s  {name}")
    skipped = sum(r["skipped"] for r in results)
    print(f"\n{a.level}: {run} tests in {wall:.1f} s: {run - len(failures) - len(errors) - skipped} passed, "
          f"{len(failures)} failed, {len(errors)} errors, {skipped} skipped", flush=True)
    known = {k: v for k, v in known.items() if ":" not in k}           # (keys of an older format)
    known.update({r["task"]: round(r["seconds"], 1) for r in results if r["run"]})
    try:
        DURATIONS.write_text(json.dumps(known, indent=1, sort_keys=True))
    except OSError:
        pass
    return 1 if failures or errors else 0


if __name__ == "__main__":
    sys.exit(main())
