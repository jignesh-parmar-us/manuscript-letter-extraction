"""Manuscript Letter Extraction: cuts letters out of scanned Devanagari manuscript pages."""

__version__ = "0.1.0"

from .heavy import limit_threads  # noqa: E402

limit_threads()                   # before NumPy and OpenCV are imported (docs/plans/done/SPEED_PLAN.md, S1)

from .config import Config, load_config  # noqa: E402,F401
