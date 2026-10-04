"""Long tasks in the background (C5c): capture a book, add new pages, cut one page again.

A job runs in a background thread of the app; the page work itself runs in worker processes, as in
the CLI (pipeline.process_folder). The screen polls the job for progress and can cancel it: the
pages already being cut finish, no further page starts, and nothing is stored.
One job per book at a time.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from .library import BookHasReviewError, Cancelled, Library, LibraryError, NotFound


@dataclass
class Job:
    id: str
    book_id: int
    kind: str                                  # capture | add_pages | recut_page
    status: str = "running"                    # running | done | failed | cancelled
    done: int = 0
    total: int = 0
    current: str = ""
    pages: List[Dict] = field(default_factory=list)   # per page: file, status, message, seconds
    result: Optional[Dict] = None
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    cancel_requested: bool = False

    def as_dict(self) -> Dict:
        d = asdict(self)
        d["seconds"] = round((self.finished or time.time()) - self.started, 1)
        return d


class Jobs:
    def __init__(self, library: Library):
        self.lib = library
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"No job {job_id}.")
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        job.cancel_requested = True
        return job

    def running_for(self, book_id: int) -> Optional[Job]:
        return next((j for j in self._jobs.values() if j.book_id == book_id and j.status == "running"), None)

    def start(self, book_id: int, kind: str, run: Callable[..., Dict], total: int = 0) -> Job:
        """`run(progress, cancel)` does the work and returns the result. `total` is the number of
        pages expected, so the screen can show "0 of 12" before the first page is done."""
        with self._lock:
            if self.running_for(book_id):
                raise LibraryError("A capture is already running for this book.")
            job = Job(id=uuid.uuid4().hex[:12], book_id=book_id, kind=kind, total=total)
            self._jobs[job.id] = job

        def progress(done, total, r):
            job.done, job.total, job.current = done, total, r.file
            job.pages.append({"file": r.file, "status": r.status, "message": r.message,
                              "seconds": round(r.seconds, 1)})

        def cancel() -> bool:
            return job.cancel_requested

        def work():
            try:
                result = run(progress, cancel)
                if job.cancel_requested:
                    job.status = "cancelled"
                else:
                    job.result, job.status = result, "done"
            except Cancelled:
                job.status = "cancelled"
            except LibraryError as e:
                job.status, job.error = "failed", str(e)
            except Exception as e:                     # shown to the user, never crashes the app
                job.status, job.error = "failed", f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                job.finished = time.time()

        threading.Thread(target=work, name=f"job-{job.id}", daemon=True).start()
        return job

    # ---- the three kinds of job ----------------------------------------------------------------
    # Cancelling: process_folder stops starting pages when cancel() is true and the library then
    # raises Cancelled before storing anything (library._run).
    def capture(self, book_id: int, force: bool = False) -> Job:
        self.lib.get_book(book_id)
        if not force and self.lib.has_manual_work(book_id):
            raise BookHasReviewError("This book has groups, labels or other changes made by hand; "
                                     "capturing again would discard them.")
        return self.start(book_id, "capture",
                          lambda progress, cancel: self.lib.capture(book_id, progress, cancel, force=force),
                          total=len(self._images(book_id)))

    def add_pages(self, book_id: int) -> Job:
        known = {p["file"] for p in self.lib.check_pages(book_id) if p["problem"] == "new"}
        return self.start(book_id, "add_pages",
                          lambda progress, cancel: self.lib.add_new_pages(book_id, progress, cancel),
                          total=len(known))

    def recut_page(self, book_id: int, page_id: int, force: bool = False) -> Job:
        if not force and self.lib.page_has_manual_work(page_id):
            raise BookHasReviewError("This page has samples that were reviewed or changed by hand; "
                                     "cutting it again would replace them.")
        return self.start(book_id, "recut_page", lambda progress, cancel:
                          self.lib.recut_page(book_id, page_id, progress, cancel, force=force), total=1)

    def _images(self, book_id: int):
        from pathlib import Path
        from .. import io_utils
        folder = Path(self.lib.get_book(book_id).input_dir)
        return io_utils.scan_folder(folder)[0] if folder.is_dir() else []
