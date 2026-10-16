"""S1 (docs/SPEED_PLAN.md): heavy jobs one at a time, one thread each, no workers left when their run is killed."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from letter_extractor import heavy                                  # noqa: E402


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class HeavyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lock = self.tmp / "heavy.lock"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_threads_are_limited_unless_already_set(self):
        self.assertEqual(os.environ.get("VECLIB_MAXIMUM_THREADS"), "1")     # set when the package was imported
        with mock.patch.dict(os.environ, {"OMP_NUM_THREADS": "3"}, clear=False):
            heavy.limit_threads()
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "3")              # the user's own setting is kept

    def test_two_heavy_jobs_run_one_after_the_other(self):
        log = self.tmp / "log"
        job = (f"import sys,time; sys.path.insert(0,{SRC!r}); from letter_extractor import heavy; heavy.WAIT=0.05\n"
               f"from pathlib import Path\n"
               f"with heavy.heavy_lock(sys.argv[1], say=lambda m: None, path=Path({str(self.lock)!r})):\n"
               f"    open({str(log)!r},'a').write(sys.argv[1]+' start\\n'); time.sleep(0.6)\n"
               f"    open({str(log)!r},'a').write(sys.argv[1]+' end\\n')\n")
        a = subprocess.Popen([sys.executable, "-c", job, "a"])
        time.sleep(0.3)
        b = subprocess.Popen([sys.executable, "-c", job, "b"])
        a.wait(20), b.wait(20)
        self.assertEqual(log.read_text().split("\n")[:4], ["a start", "a end", "b start", "b end"])
        self.assertFalse(self.lock.exists())                                 # given back

    def test_the_second_job_says_what_runs(self):
        self.lock.write_text(json.dumps({"pid": os.getppid(), "what": "full tests", "started": "now"}))
        said = []
        with mock.patch.object(heavy, "WAIT", 0.01):
            with self.assertRaises(InterruptedError):
                with heavy.heavy_lock("Measure", say=said.append, cancel=lambda: len(said) > 0, path=self.lock):
                    pass
        self.assertIn("full tests", said[0])
        self.assertTrue(self.lock.exists())                                  # still the other's

    def test_a_lock_whose_process_is_gone_is_taken_over(self):
        self.lock.write_text(json.dumps({"pid": _dead_pid(), "what": "old run", "started": ""}))
        with mock.patch.object(heavy, "stop_orphans"):
            with heavy.heavy_lock("Measure", say=lambda m: self.fail(m), path=self.lock):
                self.assertEqual(json.loads(self.lock.read_text())["pid"], os.getpid())
        self.assertFalse(self.lock.exists())

    def test_a_process_started_by_the_holder_runs_inside_its_lock(self):
        self.lock.write_text(json.dumps({"pid": os.getppid(), "what": "full tests", "started": ""}))
        with mock.patch.dict(os.environ, {heavy.HELD: str(os.getppid())}):
            with heavy.heavy_lock("a test", say=lambda m: self.fail(m), path=self.lock):
                pass
        self.assertTrue(self.lock.exists())                                  # the holder's lock is left alone

    def _killed_run(self, init: str):
        """Start a run with a pool of 2 workers (initializer `init`), kill it; the workers' pids."""
        run = (f"import sys,os,time; sys.path.insert(0,{SRC!r})\n"
               "import multiprocessing as mp\n"
               "from concurrent.futures import ProcessPoolExecutor\n"
               "from letter_extractor.heavy import worker_init\n"
               "if __name__ == '__main__':\n"
               f"    ex = ProcessPoolExecutor(2, mp_context=mp.get_context('spawn'), initializer={init})\n"
               "    list(ex.map(time.sleep, [0, 0])); print('ready', flush=True)\n"
               "    pids = [p.pid for p in ex._processes.values()]\n"
               "    ex.submit(time.sleep, 60)\n"
               "    print(' '.join(map(str, pids)), flush=True); time.sleep(60)\n")
        p = subprocess.Popen([sys.executable, "-c", run], stdout=subprocess.PIPE, text=True)
        p.stdout.readline()
        pids = [int(x) for x in p.stdout.readline().split()]
        self.assertEqual(len(pids), 2)
        os.kill(p.pid, signal.SIGKILL)                                       # the run dies, no clean-up
        p.wait()
        p.stdout.close()
        return pids

    def test_killing_a_run_leaves_no_worker(self):
        pids = self._killed_run("worker_init")
        deadline = time.time() + 10
        while time.time() < deadline and any(_alive(x) for x in pids):
            time.sleep(0.2)
        self.assertFalse([x for x in pids if _alive(x)])

    def test_left_over_workers_of_a_dead_run_are_found_and_stopped(self):
        pids = self._killed_run("None")                                      # workers without the watch
        try:
            time.sleep(0.5)
            self.assertTrue(set(pids) <= {pid for pid, _ in heavy.orphans()})
            heavy.stop_orphans(say=lambda m: None)
            deadline = time.time() + 10
            while time.time() < deadline and any(_alive(x) for x in pids):
                time.sleep(0.2)
            self.assertFalse([x for x in pids if _alive(x)])
        finally:
            for x in pids:
                if _alive(x):
                    os.kill(x, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
