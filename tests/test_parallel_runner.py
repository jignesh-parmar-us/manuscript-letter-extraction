"""S2 (docs/plans/done/SPEED_PLAN.md): tools/test_parallel.py runs the same tests as `unittest discover`, `fast` without
the sample-page and end-to-end classes, the sample-page tests together in one task."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

spec = importlib.util.spec_from_file_location("test_parallel_tool", ROOT / "tools" / "test_parallel.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

MODULES = ["test_lines", "test_library", "test_heavy"]


def ids(tests):
    return sorted(t.id() for t in tests)


class RunnerTests(unittest.TestCase):
    def test_full_runs_every_test_once_and_fast_leaves_out_the_heavy_classes(self):
        loader = unittest.TestLoader()
        every = ids(t for m in MODULES for t in tool._flatten(loader.loadTestsFromName(m)))
        tasks = [f"{m}.{c}" for m in MODULES for c in tool._classes(m)]
        full = ids([t for task in tasks for t in tool._tests(task, "full", MODULES)]
                   + tool._tests(tool.SAMPLES_TASK, "full", MODULES))
        self.assertEqual(full, every)                                        # each once, none lost
        fast = ids(t for task in tasks for t in tool._tests(task, "fast", MODULES))
        left_out = set(every) - set(fast)
        self.assertIn("test_lines.SamplePageLinesTests.test_eleven_lines_on_every_sample_page", left_out)
        self.assertIn("test_library.SampleBookTests.test_sample_pages_as_a_book", left_out)
        self.assertTrue(all(".Sample" in x for x in left_out), left_out)
        samples = ids(tool._tests(tool.SAMPLES_TASK, "full", MODULES))
        self.assertEqual(samples, ["test_lines.SamplePageLinesTests.test_eleven_lines_on_every_sample_page"])

    def test_helper_classes_are_not_tests(self):
        self.assertIn("WidthReader", tool._classes("test_segment"))          # a helper class, not a TestCase
        self.assertEqual(tool._tests("test_segment.WidthReader", "fast", MODULES), [])


if __name__ == "__main__":
    unittest.main()
