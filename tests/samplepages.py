"""The sample pages (samples/page1.jpg, page2.jpg) cut once per test process and shared by the sample-page tests
(lines, pieces, letters, grouping; docs/plans/done/SPEED_PLAN.md S2). tools/test_parallel.py runs those tests in one
process, so each page is cut once per test run."""
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from letter_extractor import io_utils                               # noqa: E402
from letter_extractor.config import Config                          # noqa: E402
from letter_extractor.pipeline import PageData, process_page        # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
PRESENT = (SAMPLES / "page1.jpg").is_file()
LEVEL = "samples"            # tools/test_parallel.py: a class with this LEVEL runs in `full` only, in one process


@lru_cache(maxsize=None)
def processed(name: str) -> PageData:
    """Every step for one sample page with the default settings (pipeline.process_page). Do not change it."""
    rgb, _ = io_utils.load_image(SAMPLES / name)
    return process_page(rgb, Config())
