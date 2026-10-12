"""The backend API of the review app (C5c), a FastAPI application.

`create_app(library, token)` returns the app. It is meant to listen on 127.0.0.1 only (see main.py,
C5d). Every request must carry the session token, created when the app starts: in the `X-Token`
header, or as `?token=` for images (an <img> tag cannot send headers). Other web pages open in the
same browser therefore cannot use the API.

Routes (all JSON unless noted):
  books      GET/POST /api/books (the folder of page images optional), GET/PATCH/DELETE /api/books/{id},
             POST /api/books/{id}/folder (the Training Data page images), GET /api/books/{id}/page-problems
  jobs       POST /api/books/{id}/capture | /add-pages | /pages/{page_id}/recut | /suggest (C11) | /fix-cuts (C12b),
             GET /api/jobs/{job}, POST /api/jobs/{job}/cancel
  ocr (C11)  GET /api/tesseract (installed? version, languages); groups carry `suggestion` and `readings`,
             their samples and unsure samples `reading`, the book `ocr_runs`;
             GET /api/groups/{id}/read-as?text=... (sample ids), GET /api/books/{id}/suggestion-accuracy[?engine=]
             (C12); POST /api/books/{id}/suggest {"engine": "books"} and GET /api/books/{id}/reference-books
             (C13): suggestions from the labelled groups of other books; groups also carry `other_suggestion`
  reading    GET /api/books/{id}/pages, /api/pages/{id}, /api/books/{id}/groups, /api/groups/{id},
             /api/groups/{id}/samples, /api/books/{id}/unsure, /api/samples/{id}
  actions    POST /api/books/{id}/actions/{move|new-group|merge|dissolve|label|status|delete|restore},
             POST /api/books/{id}/actions/{accept-suggestions|reject-suggestion|label-samples} (C12),
             POST /api/books/{id}/actions/split-mixed (C12d), /actions/remove-readings (wrong readings),
             POST /api/books/{id}/undo | /redo, GET /api/books/{id}/history
  labels     GET /api/label?text=...&book_id=...   (with a book: `used_by`, the groups with that label)
  files      GET /files/books/{id}/{path} (letter, mask and line images), GET /files/pages/{page_id}
             (the input page image)
  samples    POST /api/books/{id}/samples/{crop|join|split|upload}   (C5f)
  generated  POST /api/books/{id}/generate-letters (a job, printed books): the missing letters of the letter
             table made from the book's own letters (generate.py); groups carry `generated`, how many of
             their letters were made so
  export     POST /api/books/{id}/export (a job), POST /api/app/open-folder   (C5g)
  app (C5d)  GET /api/app, POST /api/app/library, POST /api/app/pick-folder,
             PATCH /api/books/{id}/settings; GET / serves the built screen with the token in it;
             GET /help/<page> the help pages (no token), POST /api/app/open-help (window mode)
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from .. import __version__
from ..config import Config, load_config
from ..mapping import describe, mapping_for
from . import actions, samples as manual
from .centres import suggestions
from .db import GENERATED, Book, LetterGroup, Line, Page, Sample
from .jobs import Jobs
from .library import BookHasReviewError, Library, LibraryError, NotFound
from .schemas import (AcceptSuggestions, LineSearchRequest, BookCreate, BookUpdate, BookSettings, Crop, ExportRequest, FolderPath, Force,
                      ConvertRequest, PagePart, Proofread, ReadSource, ReaderChoice, TrainRequest, WordListImport, WordListUse, LineTruthText, WholeLineEdit,
                      GroupRef, HelpPage, Label, LabelSamples, LibraryChoice, Merge, Move, RejectSuggestion,
                      RemoveReadings, SampleIds, Split, Status, SuggestRequest, Upload)
from .suggest import (group_suggestions, latest_runs, reference_books, sample_readings, samples_read_as,
                      suggestion_accuracy)

MAX_PAGE = 500


def _book_json(b: Dict) -> Dict:
    out = dict(b)
    for k in ("created_at", "updated_at", "captured_at"):
        out[k] = out[k].isoformat() if out.get(k) else None
    return out


def _sample_json(smp: Sample, book_id: int, token: str) -> Dict:
    # the session keeps loaded pages, so a grid of samples from a few pages costs a few lookups
    page = object_session(smp).get(Page, smp.page_id) if smp.page_id is not None else None
    return {"id": smp.id, "page_id": smp.page_id, "page_file": page.file if page else None,
            "line": smp.line_number, "pos": smp.pos,
            "box": [smp.x, smp.y, smp.w, smp.h], "ink": smp.ink, "kind": smp.kind, "source": smp.source,
            "group_id": smp.group_id, "distance": None if smp.distance is None else round(smp.distance, 3),
            "deleted": smp.deleted, "rules": smp.rules,
            "image": f"/files/books/{book_id}/{smp.image}?token={token}",
            "context": f"/files/samples/{smp.id}/context?token={token}" if smp.page_id is not None else None}


def _group_members(s, book_id: int, group_id: Optional[int] = None) -> Dict[int, List]:
    """The members of a book's groups (or of one group) as light rows (id, ink, distance, image, source), nearest
    to the centre first: one query for all groups, without the fingerprints."""
    q = (select(Sample.group_id, Sample.id, Sample.ink, Sample.distance, Sample.image, Sample.source)
         .where(Sample.book_id == book_id, Sample.group_id.is_not(None), Sample.deleted.is_(False)))
    if group_id is not None:
        q = q.where(Sample.group_id == group_id)
    out: Dict[int, List] = {}
    for row in s.execute(q.order_by(Sample.distance)):
        out.setdefault(row.group_id, []).append(row)
    return out


def _group_json(s, g: LetterGroup, token: str, ocr: Optional[Dict] = None, mem: Optional[List] = None) -> Dict:
    """`ocr`: the group's entry of suggest.group_readings (suggestion and most common readings); `mem`:
    its members from _group_members, if already known."""
    if mem is None:
        mem = _group_members(s, g.book_id, g.id).get(g.id, [])
    red = sum(m.ink == "red" for m in mem)
    dists = [m.distance for m in mem if m.distance is not None]
    return {"id": g.id, "code": g.code, "kind": g.kind, "label_dev": g.label_dev, "label_guj": g.label_guj,
            "status": g.status, "locked": g.locked, "samples": len(mem), "red": red, "black": len(mem) - red,
            "generated": sum(m.source == GENERATED for m in mem),     # letters made by the system (generate.py)
            "spread": round(sum(dists) / len(dists), 3) if dists else None,
            "example_id": mem[0].id if mem else None,
            "example_image": f"/files/books/{g.book_id}/{mem[0].image}?token={token}" if mem else None,
            "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            "suggestion": (ocr or {}).get("suggestion"), "other_suggestion": (ocr or {}).get("other_suggestion"),
            "readings": (ocr or {}).get("readings", []), "read": (ocr or {}).get("read", 0)}


def create_app(library: Library, token: str, context=None) -> FastAPI:
    """`context` (main.AppContext) tells the screens how the app runs; tests may leave it out."""
    from .main import AppContext, save_settings
    context = context or AppContext()
    app = FastAPI(title="Manuscript Letter Extraction", version=__version__)
    jobs = Jobs(library)
    app.state.library, app.state.jobs, app.state.token = library, jobs, token

    def check_token(x_token: Optional[str] = Header(default=None), q_token: Optional[str] = Query(default=None,
                                                                                                    alias="token")):
        if token and (x_token or q_token) != token:
            raise HTTPException(status_code=401, detail="Missing or wrong session token.")

    auth = [Depends(check_token)]

    @app.exception_handler(BookHasReviewError)
    async def _needs_confirmation(request: Request, e: BookHasReviewError):
        return JSONResponse(status_code=409, content={"detail": str(e), "code": "needs_confirmation"})

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, e: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(e)})

    @app.exception_handler(LibraryError)
    async def _library_error(request: Request, e: LibraryError):
        return JSONResponse(status_code=400, content={"detail": str(e)})

    def book_or_404(s, book_id: int) -> Book:
        b = s.get(Book, book_id)
        if b is None:
            raise HTTPException(404, f"No book with id {book_id}.")
        return b

    def group_or_404(s, group_id: int) -> LetterGroup:
        g = s.get(LetterGroup, group_id)
        if g is None:
            raise HTTPException(404, f"No group with id {group_id}.")
        return g

    # ---- books -----------------------------------------------------------------------------------
    @app.get("/api/books", dependencies=auth)
    def list_books() -> List[Dict]:
        return [_book_json(b) for b in library.list_books()]

    @app.post("/api/books", dependencies=auth, status_code=201)
    def create_book(body: BookCreate) -> Dict:
        try:
            cfg = load_config(None, **body.settings) if body.settings else None
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Settings: {e}")
        book = library.create_book(body.name, Path(body.input_dir) if body.input_dir.strip() else None, cfg,
                                   body.writing)
        return get_book(book.id)

    @app.post("/api/books/{book_id}/folder", dependencies=auth)
    def input_folder(book_id: int, body: FolderPath) -> Dict:
        library.set_input_folder(book_id, Path(body.path))
        return get_book(book_id)

    @app.get("/api/books/{book_id}", dependencies=auth)
    def get_book(book_id: int) -> Dict:
        summary = next((b for b in library.list_books() if b["id"] == book_id), None)
        if summary is None:
            raise HTTPException(404, f"No book with id {book_id}.")
        book = library.get_book(book_id)
        undo_redo = actions.can_undo_redo(library, book_id)
        running = jobs.running_for(book_id)
        with library.session() as s:
            runs = [{"engine": r.engine, "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                     "result": json.loads(r.result or "{}")} for r in latest_runs(s, book_id)]
        return {**_book_json(summary), "settings": json.loads(book.settings), "undo": undo_redo["undo"],
                "redo": undo_redo["redo"], "job": running.as_dict() if running else None, "ocr_runs": runs}

    @app.patch("/api/books/{book_id}", dependencies=auth)
    def update_book(book_id: int, body: BookUpdate) -> Dict:
        if body.name is not None:
            library.rename_book(book_id, body.name)
        if body.writing is not None:
            library.set_book_writing(book_id, body.writing)
        return get_book(book_id)

    @app.delete("/api/books/{book_id}", dependencies=auth, status_code=204)
    def delete_book(book_id: int) -> None:
        if jobs.running_for(book_id):
            raise HTTPException(409, "A capture is running for this book.")
        library.delete_book(book_id)

    @app.get("/api/books/{book_id}/page-problems", dependencies=auth)
    def page_problems(book_id: int, part: str = Query("training", pattern="^(training|read)$")) -> List[Dict]:
        return library.check_pages(book_id, part)

    # ---- Read Book (C16a) -----------------------------------------------------------------------------
    @app.post("/api/books/{book_id}/read/folder", dependencies=auth)
    def read_folder(book_id: int, body: ReadSource) -> Dict:
        library.set_read_folder(book_id, Path(body.path), force=body.force)
        return get_book(book_id)

    @app.post("/api/books/{book_id}/read/pdf", dependencies=auth, status_code=202)
    def read_pdf(book_id: int, body: ReadSource) -> Dict:
        return jobs.import_pdf(book_id, body.path, force=body.force).as_dict()

    @app.post("/api/books/{book_id}/read/capture", dependencies=auth, status_code=202)
    def read_capture(book_id: int) -> Dict:
        return jobs.capture_read(book_id).as_dict()

    # ---- converted text (C16b) ---------------------------------------------------------------------
    @app.post("/api/books/{book_id}/convert", dependencies=auth, status_code=202)
    def convert(book_id: int, body: ConvertRequest = ConvertRequest()) -> Dict:
        return jobs.convert(book_id, body.page_ids, body.part, tesseract_path=tesseract_setting(),
                            mode=body.mode).as_dict()

    @app.get("/api/pages/{page_id}/whole-lines", dependencies=auth)
    def whole_lines_of_page(page_id: int, engine: str = Query("tesseract", pattern="^(tesseract|search)$")) -> Dict:
        """A page's lines read whole by Tesseract or by the line search (no letter cutting)."""
        from .wholelines import page_whole_lines
        got = page_whole_lines(library, page_id, engine)
        if got is None:
            raise HTTPException(404, "This page's lines are not read yet.")
        with library.session() as s:
            book_id = s.get(Page, page_id).book_id
        for ln in got["lines"]:
            ln["image"] = f"/files/books/{book_id}/{ln['image']}?token={token}" if ln.get("image") else None
        return got

    @app.put("/api/lines/{line_id}/whole", dependencies=auth)
    def edit_whole_line(line_id: int, body: WholeLineEdit) -> Dict:
        """Correct a line read whole and / or mark it reviewed (a reviewed line becomes a checked line)."""
        from .wholelines import set_whole_line
        return set_whole_line(library, line_id, body.text, body.reviewed, body.shown)

    @app.post("/api/books/{book_id}/line-search", dependencies=auth, status_code=202)
    def line_search(book_id: int, body: LineSearchRequest = LineSearchRequest()) -> Dict:
        """The line search's second opinion on the pages read whole (a job)."""
        return jobs.line_search(book_id, body.page_ids, body.part, body.retrain).as_dict()

    @app.get("/api/books/{book_id}/line-search", dependencies=auth)
    def line_search_reader(book_id: int) -> Dict:
        """The book's line-search reader (what it was trained on, or null) and its last measure (or null)."""
        from .linesearch import last_measure, line_reader_info
        m = last_measure(library, book_id)
        return {"reader": line_reader_info(library, book_id), "measure": m}

    @app.post("/api/books/{book_id}/line-search/measure", dependencies=auth, status_code=202)
    def line_search_measure(book_id: int) -> Dict:
        """Score the line search fold-fair on the checked lines (a job)."""
        return jobs.line_search_measure(book_id).as_dict()

    @app.get("/api/books/{book_id}/whole-lines", dependencies=auth)
    def whole_lines_of_book(book_id: int, part: str = Query("read", pattern="^(training|read)$"),
                            engine: str = Query("tesseract", pattern="^(tesseract|search)$")) -> List[Dict]:
        from .wholelines import book_whole_lines
        library.get_book(book_id)
        return book_whole_lines(library, book_id, part, engine)

    @app.get("/api/pages/{page_id}/text", dependencies=auth)
    def text_of_page(page_id: int) -> Dict:
        from .texts import page_text
        got = page_text(library, page_id)
        if got is None:
            raise HTTPException(404, "This page is not converted yet.")
        return with_images(got)

    def with_images(got: Dict) -> Dict:
        with library.session() as s:
            book_id = s.get(Page, got["page_id"]).book_id
        for line in got["lines"]:
            for x in line:
                x["image"] = f"/files/books/{book_id}/{x['image']}?token={token}" if x.get("image") else None
        return got

    @app.post("/api/pages/{page_id}/proofread", dependencies=auth)
    def proofread_line(page_id: int, body: Proofread) -> Dict:
        """Mark a line proofread (its text as it is now is kept) or not (C17)."""
        from .texts import set_proofread
        return with_images(set_proofread(library, page_id, body.line, body.proofread))

    @app.get("/api/books/{book_id}/proofread-stats", dependencies=auth)
    def proofread_stats_of_book(book_id: int, part: str = Query("read", pattern="^(training|read)$")) -> Dict:
        """How right the conversion was on the proofread lines (C17)."""
        from .texts import proofread_stats
        library.get_book(book_id)
        return proofread_stats(library, book_id, part)

    @app.get("/api/books/{book_id}/texts", dependencies=auth)
    def texts_of_book(book_id: int, part: str = Query("read", pattern="^(training|read)$")) -> List[Dict]:
        """Which pages of a part are converted, with their numbers of uncertain letters and proofread lines."""
        from .texts import book_page_texts
        library.get_book(book_id)
        return [{"page_id": p.id, "uncertain": t["uncertain"], "proofread": t["proofread"], "lines": len(t["lines"]),
                 "converted_at": t["converted_at"]}
                for p, t in book_page_texts(library, book_id, part)]

    @app.get("/files/texts/{book_id}", dependencies=auth)
    def download_text(book_id: int, format: str = Query("txt", pattern="^(txt|docx)$"),
                      page_id: Optional[int] = None, script: str = Query("gujarati", pattern="^(gujarati|devanagari)$"),
                      part: str = Query("read", pattern="^(training|read)$"),
                      marker: Optional[str] = Query(None, pattern="^(mark|guess|none)$"),
                      readers: str = Query("both", pattern="^(both|tesseract|lines|lines_lm|search)$")):
        """The text of one page or of every converted page of a part, as .txt (UTF-8) or Word."""
        from urllib.parse import quote
        from ..mapping import mapping_for
        from ..ocr.docx import write_docx
        from .texts import book_page_texts, marked_lines
        book = library.get_book(book_id)
        cfg = library.book_config(book)
        mapping = mapping_for(cfg)
        if readers in ("lines", "lines_lm", "search"):   # lines read whole by Tesseract (+ the language
            from .wholelines import whole_line_texts      # model), or by the line search (our reader)
            rows = whole_line_texts(library, book_id, part, page_id, "search" if readers == "search" else "tesseract")
            if not rows:
                raise HTTPException(404, "No lines read yet.")
            mark = marker or cfg.uncertain_marker

            def line_of(ln):
                if ln.get("edited_dev"):                     # the user's correction wins
                    return ln["edited_guj"] if script == "gujarati" else ln["edited_dev"]
                out = ""
                for x in ln["aksharas"]:
                    t = x.get("lm_dev", x["text_dev"]) if readers == "lines_lm" else x["text_dev"]
                    if x["uncertain"] and mark != "none":
                        t = f"[?{t}]" if mark == "guess" else "[?]"
                    out += (" " if x["space"] else "") + t
                return mapping.gujarati(out) if script == "gujarati" else out
            pages = [(f"{p.number or i} · {p.file}" if not page_id else "", [line_of(ln) for ln in lines])
                     for i, (p, lines) in enumerate(rows, 1)]
        else:
            rows = book_page_texts(library, book_id, part, page_id)
            if not rows:
                raise HTTPException(404, "Nothing converted yet.")
            pages = [(f"{p.number or i} · {p.file}" if not page_id else "",
                      marked_lines(t["lines"], marker or cfg.uncertain_marker, script, mapping, readers))
                     for i, (p, t) in enumerate(rows, 1)]
        name = Path(rows[0][0].file).stem if page_id else book.name
        if format == "docx":
            data = write_docx(pages)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            parts = [("" if not heading else f"=== {heading} ===\n") + "\n".join(lines) for heading, lines in pages]
            data = ("\n\n".join(parts) + "\n").encode("utf-8")
            media = "text/plain; charset=utf-8"
        disposition = f"attachment; filename*=UTF-8''{quote(name)}.{format}"
        return Response(data, media_type=media, headers={"Content-Disposition": disposition})

    # ---- the line truth screen: checked text of whole lines ---------------------------------------------
    @app.get("/api/books/{book_id}/truth", dependencies=auth)
    def truth_progress(book_id: int, part: str = Query("read", pattern="^(training|read)$")) -> Dict:
        from .truth import book_progress
        library.get_book(book_id)
        return book_progress(library, book_id, part)

    @app.get("/api/pages/{page_id}/truth", dependencies=auth)
    def truth_lines(page_id: int) -> List[Dict]:
        from .truth import page_lines
        lines = page_lines(library, page_id)
        with library.session() as s:
            book_id = s.get(Page, page_id).book_id
        for ln in lines:
            ln["image"] = f"/files/books/{book_id}/{ln['image']}?token={token}"
        return lines

    @app.get("/api/lines/{line_id}/tesseract", dependencies=auth)
    def line_tesseract(line_id: int) -> Dict:
        """Tesseract's reading of the whole line, without letter cutting."""
        from .suggest import tesseract_reader
        from .truth import tesseract_text
        with library.session() as s:
            line = s.get(Line, line_id)
            if line is None:
                raise HTTPException(404, f"No line with id {line_id}.")
            book = s.get(Book, s.get(Page, line.page_id).book_id)
            cfg = library.book_config(book)
        return tesseract_text(library, line_id, tesseract_reader(cfg, tesseract_setting()))

    @app.put("/api/lines/{line_id}/truth", dependencies=auth)
    def line_truth(line_id: int, body: LineTruthText) -> Dict:
        from .truth import save_truth
        return save_truth(library, line_id, body.text, body.tesseract) or {"line_id": line_id, "truth_dev": None,
                                                                             "truth_guj": None}

    # ---- the language model and its word lists (C15) ---------------------------------------------------
    @app.get("/api/wordlists", dependencies=auth)
    def list_word_lists() -> List[Dict]:
        from .dictionary import word_lists
        return word_lists(library)

    @app.post("/api/wordlists", dependencies=auth)
    def import_list(body: WordListImport) -> Dict:
        from .dictionary import import_word_list
        if body.book_id is not None:
            library.get_book(body.book_id)
        return import_word_list(library, body.path, body.name, [body.book_id] if body.book_id is not None else [])

    @app.patch("/api/wordlists/{list_id}", dependencies=auth)
    def use_list(list_id: int, body: WordListUse) -> Dict:
        from .dictionary import use_word_list
        library.get_book(body.book_id)
        return use_word_list(library, list_id, body.book_id, body.use)

    @app.delete("/api/wordlists/{list_id}", dependencies=auth, status_code=204)
    def delete_list(list_id: int) -> Response:
        from .dictionary import delete_word_list
        delete_word_list(library, list_id)
        return Response(status_code=204)

    @app.get("/api/books/{book_id}/language", dependencies=auth)
    def language_of_book(book_id: int) -> Dict:
        """What the book's language model learns from (C15)."""
        from .dictionary import book_language
        return book_language(library, book_id)

    # ---- letter readers (C14) ------------------------------------------------------------------------
    def reader_json(r, full: bool = False) -> Dict:
        acc = json.loads(r.accuracy or "{}")
        out = {"id": r.id, "name": r.name, "kind": r.kind, "created_at": r.created_at.isoformat() if r.created_at else None,
               "trained_on": json.loads(r.trained_on or "{}"), "accuracy": acc.get("overall"),
               "accuracy_20": acc.get("labels_20"), "labels": len(json.loads(r.classes or "[]"))}
        if full:
            report = json.loads(r.report or "{}")
            out.update(per_label=acc.get("per_label", []), confusions=report.get("confusions", []),
                       check=len(report.get("check", [])), seconds=report.get("seconds"))
        return out

    @app.post("/api/books/{book_id}/train", dependencies=auth, status_code=202)
    def train(book_id: int, body: TrainRequest = TrainRequest()) -> Dict:
        return jobs.train(book_id, body.books, body.min_samples, body.include_unreviewed, body.include_words,
                          body.name).as_dict()

    @app.get("/api/readers", dependencies=auth)
    def readers() -> List[Dict]:
        from .db import Reader
        with library.session() as s:
            return [reader_json(r) for r in s.scalars(select(Reader).order_by(Reader.id.desc()))]

    @app.get("/api/readers/{reader_id}", dependencies=auth)
    def reader(reader_id: int) -> Dict:
        from .db import Reader
        with library.session() as s:
            r = s.get(Reader, reader_id)
            if r is None:
                raise HTTPException(404, f"No reader with id {reader_id}.")
            return reader_json(r, full=True)

    @app.delete("/api/readers/{reader_id}", dependencies=auth, status_code=204)
    def delete_reader(reader_id: int) -> None:
        from .readers import delete_reader as remove
        remove(library, reader_id)

    @app.post("/api/books/{book_id}/reader", dependencies=auth, status_code=202)
    def use_reader(book_id: int, body: ReaderChoice) -> Dict:
        return jobs.use_reader(book_id, body.reader_id).as_dict()

    @app.get("/api/books/{book_id}/check", dependencies=auth)
    def check_these(book_id: int) -> List[Dict]:
        """The active reader's letters that are probably in the wrong group."""
        from .readers import check_list
        items = check_list(library, book_id)
        with library.session() as s:
            out = []
            for c in items:
                smp = s.get(Sample, c["sample_id"])
                g = s.get(LetterGroup, c["group_id"])
                mapping = mapping_for(library.book_config(library.get_book(book_id)))
                out.append({**c, "sample": _sample_json(smp, book_id, token), "group_code": g.code,
                            "label_guj": mapping.gujarati(c["label"]), "read_guj": mapping.gujarati(c["read"])})
            return out

    @app.post("/api/pages/{page_id}/part", dependencies=auth)
    def page_part(page_id: int, body: PagePart) -> Dict:
        return library.set_page_part(page_id, body.part, force=body.force)

    # ---- jobs --------------------------------------------------------------------------------------
    @app.post("/api/books/{book_id}/capture", dependencies=auth, status_code=202)
    def capture(book_id: int, body: Force = Force()) -> Dict:
        return jobs.capture(book_id, force=body.force).as_dict()

    @app.post("/api/books/{book_id}/add-pages", dependencies=auth, status_code=202)
    def add_pages(book_id: int) -> Dict:
        return jobs.add_pages(book_id).as_dict()

    @app.post("/api/books/{book_id}/pages/{page_id}/recut", dependencies=auth, status_code=202)
    def recut(book_id: int, page_id: int, body: Force = Force()) -> Dict:
        return jobs.recut_page(book_id, page_id, force=body.force).as_dict()

    def tesseract_setting() -> str:
        from .main import load_settings
        return str(load_settings(context.settings_file).get("tesseract_path", ""))   # app setting, not per book

    @app.post("/api/books/{book_id}/suggest", dependencies=auth, status_code=202)
    def suggest(book_id: int, body: SuggestRequest = SuggestRequest()) -> Dict:
        return jobs.suggest(book_id, body.engine, tesseract_setting(), body.books).as_dict()

    @app.get("/api/books/{book_id}/reference-books", dependencies=auth)
    def ref_books(book_id: int) -> List[Dict]:
        """The other books with labelled groups, for suggestions from labelled books (C13)."""
        return reference_books(library, book_id)

    @app.post("/api/books/{book_id}/fix-cuts", dependencies=auth, status_code=202)
    def fix_cuts(book_id: int) -> Dict:
        book = library.get_book(book_id)
        if book.writing != "printed":
            raise HTTPException(400, "Fixing cuts with Tesseract is for printed books.")
        return jobs.fix_cuts(book_id).as_dict()

    @app.post("/api/books/{book_id}/fix-bars", dependencies=auth, status_code=202)
    def fix_bars(book_id: int) -> Dict:
        book = library.get_book(book_id)
        if book.writing != "printed":
            raise HTTPException(400, "Fixing aa bars is for printed books.")
        return jobs.fix_bars(book_id).as_dict()

    @app.get("/api/tesseract", dependencies=auth)
    def tesseract(book_id: Optional[int] = None) -> Dict:
        """Whether Tesseract can run, and with the book's languages (C11; the C12 button uses it)."""
        from ..ocr.tesseract import TesseractError, find_tesseract
        langs = library.book_config(library.get_book(book_id)).ocr_langs if book_id else Config().ocr_langs
        try:
            engine = find_tesseract(tesseract_setting())
            engine.check_langs(langs)
        except TesseractError as e:
            return {"ok": False, "error": str(e), "langs_needed": langs}
        return {"ok": True, "path": engine.path, "version": engine.version, "langs": engine.langs,
                "langs_needed": langs}

    @app.post("/api/books/{book_id}/export", dependencies=auth, status_code=202)
    def export(book_id: int, body: ExportRequest = ExportRequest()) -> Dict:
        from .export import IMAGE_MODES
        if body.image is not None and body.image not in IMAGE_MODES:
            raise HTTPException(400, f"Image mode must be one of {', '.join(IMAGE_MODES)}.")
        folder = Path(body.folder).expanduser() if body.folder else None
        if folder is not None and folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise HTTPException(400, f"The export folder must be new or empty: {folder}")
        return jobs.export(book_id, folder, body.image).as_dict()

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def job(job_id: str) -> Dict:
        return jobs.get(job_id).as_dict()

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: str) -> Dict:
        return jobs.cancel(job_id).as_dict()

    # ---- reading -----------------------------------------------------------------------------------
    @app.get("/api/books/{book_id}/pages", dependencies=auth)
    def pages(book_id: int, part: str = Query("training", pattern="^(training|read)$")) -> List[Dict]:
        with library.session() as s:
            book_or_404(s, book_id)
            out = []
            for p in s.scalars(select(Page).where(Page.book_id == book_id, Page.part == part)
                               .order_by(Page.number, Page.id)):
                n = s.scalar(select(func.count(Sample.id)).where(Sample.page_id == p.id, Sample.deleted.is_(False)))
                out.append({"id": p.id, "file": p.file, "width": p.width, "height": p.height, "status": p.status,
                            "message": p.message, "lines": len(p.lines), "samples": n, "part": p.part,
                            "number": p.number,
                            "image": f"/files/pages/{p.id}?token={token}"})
            return out

    @app.get("/api/pages/{page_id}", dependencies=auth)
    def page(page_id: int) -> Dict:
        with library.session() as s:
            p = s.get(Page, page_id)
            if p is None:
                raise HTTPException(404, f"No page with id {page_id}.")
            samples = s.scalars(select(Sample).where(Sample.page_id == page_id, Sample.deleted.is_(False))
                                .order_by(Sample.line_number, Sample.pos)).all()
            return {"id": p.id, "book_id": p.book_id, "file": p.file, "width": p.width, "height": p.height,
                    "status": p.status, "message": p.message, "line_spacing": p.line_spacing, "part": p.part,
                    "image": f"/files/pages/{p.id}?token={token}",
                    "lines": [{"id": ln.id, "number": ln.number, "box": [ln.x, ln.y, ln.w, ln.h], "ink": ln.ink,
                               "image": f"/files/books/{p.book_id}/{ln.image}?token={token}"} for ln in p.lines],
                    "samples": [_sample_json(smp, p.book_id, token) for smp in samples]}

    @app.post("/api/books/{book_id}/generate-letters", dependencies=auth, status_code=202)
    def generate_letters(book_id: int) -> Dict:
        book = library.get_book(book_id)
        if book.writing != "printed":
            raise HTTPException(400, "Generating missing letters is for printed books for now.")
        return jobs.generate_letters(book_id).as_dict()

    @app.get("/api/books/{book_id}/groups", dependencies=auth)
    def groups(book_id: int) -> List[Dict]:
        with library.session() as s:
            book = book_or_404(s, book_id)
            ocr = group_suggestions(s, book, library.book_config(book))
            mem = _group_members(s, book_id)
            return [_group_json(s, g, token, ocr.get(g.id), mem.get(g.id, [])) for g in
                    s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id).order_by(LetterGroup.code))]

    @app.get("/api/groups/{group_id}", dependencies=auth)
    def group(group_id: int) -> Dict:
        with library.session() as s:
            g = group_or_404(s, group_id)
            book = s.get(Book, g.book_id)
            ocr = group_suggestions(s, book, library.book_config(book), [g.id])
            return _group_json(s, g, token, ocr.get(g.id))

    @app.get("/api/groups/{group_id}/samples", dependencies=auth)
    def group_samples(group_id: int, offset: int = 0, limit: int = Query(200, le=MAX_PAGE)) -> Dict:
        with library.session() as s:
            g = group_or_404(s, group_id)
            q = select(Sample).where(Sample.group_id == g.id, Sample.deleted.is_(False))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(Sample.distance, Sample.id).offset(offset).limit(limit)).all()
            book = s.get(Book, g.book_id)
            reads = sample_readings(s, book, library.book_config(book), [x.id for x in rows], unsure=False)
            return {"total": total, "offset": offset,
                    "samples": [{**_sample_json(x, g.book_id, token), "reading": reads.get(x.id)} for x in rows]}

    @app.get("/api/groups/{group_id}/read-as", dependencies=auth)
    def group_read_as(group_id: int, text: str) -> Dict:
        """The ids of the group's samples read as `text` (all of them, not one page)."""
        with library.session() as s:
            g = group_or_404(s, group_id)
            return {"ids": samples_read_as(s, s.get(Book, g.book_id), g.id, text)}

    @app.get("/api/books/{book_id}/suggestion-accuracy", dependencies=auth)
    def accuracy(book_id: int, engine: Optional[str] = None) -> Dict:
        with library.session() as s:
            book = book_or_404(s, book_id)
            return suggestion_accuracy(s, book, library.book_config(book), engine)

    @app.get("/api/books/{book_id}/unsure", dependencies=auth)
    def unsure(book_id: int, offset: int = 0, limit: int = Query(200, le=MAX_PAGE),
               suggest: bool = True, deleted: bool = False) -> Dict:
        with library.session() as s:
            book = book_or_404(s, book_id)
            q = select(Sample).where(Sample.book_id == book_id, Sample.part == "training", Sample.deleted.is_(deleted))
            if not deleted:
                q = q.where(Sample.group_id.is_(None))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(Sample.page_id, Sample.line_number, Sample.pos).offset(offset).limit(limit)).all()
            cfg = library.book_config(book)
            sugg = suggestions(s, book_id, rows, cfg.group_distance) if suggest else {}
            reads = sample_readings(s, book, cfg, [x.id for x in rows])
            return {"total": total, "offset": offset,
                    "samples": [{**_sample_json(x, book_id, token), "suggestion": sugg.get(x.id),
                                 "reading": reads.get(x.id)} for x in rows]}

    @app.get("/api/samples/{sample_id}", dependencies=auth)
    def sample(sample_id: int) -> Dict:
        with library.session() as s:
            smp = s.get(Sample, sample_id)
            if smp is None:
                raise HTTPException(404, f"No sample with id {sample_id}.")
            return _sample_json(smp, smp.book_id, token)

    # ---- actions -----------------------------------------------------------------------------------
    def after(book_id: int, result: Dict) -> Dict:
        return {**result, **actions.can_undo_redo(library, book_id)}

    @app.post("/api/books/{book_id}/actions/move", dependencies=auth)
    def a_move(book_id: int, body: Move) -> Dict:
        return after(book_id, actions.move_samples(library, book_id, body.sample_ids, body.group_id))

    @app.post("/api/books/{book_id}/actions/new-group", dependencies=auth)
    def a_new_group(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.new_group(library, book_id, body.sample_ids))

    @app.post("/api/books/{book_id}/actions/merge", dependencies=auth)
    def a_merge(book_id: int, body: Merge) -> Dict:
        return after(book_id, actions.merge_groups(library, book_id, body.target_id, body.source_ids))

    @app.post("/api/books/{book_id}/actions/dissolve", dependencies=auth)
    def a_dissolve(book_id: int, body: GroupRef) -> Dict:
        return after(book_id, actions.dissolve_group(library, book_id, body.group_id))

    @app.post("/api/books/{book_id}/actions/label", dependencies=auth)
    def a_label(book_id: int, body: Label) -> Dict:
        return after(book_id, actions.set_label(library, book_id, body.group_id, body.text))

    @app.post("/api/books/{book_id}/actions/accept-suggestions", dependencies=auth)
    def a_accept(book_id: int, body: AcceptSuggestions) -> Dict:
        return after(book_id, actions.accept_suggestions(library, book_id, [i.model_dump() for i in body.items]))

    @app.post("/api/books/{book_id}/actions/reject-suggestion", dependencies=auth)
    def a_reject(book_id: int, body: RejectSuggestion) -> Dict:
        return after(book_id, actions.reject_suggestion(library, book_id, body.group_id, body.label_dev))

    @app.post("/api/books/{book_id}/actions/split-mixed", dependencies=auth)
    def a_split_mixed(book_id: int) -> Dict:
        library.get_book(book_id)
        return after(book_id, actions.split_mixed(library, book_id))

    @app.post("/api/books/{book_id}/actions/remove-readings", dependencies=auth)
    def a_remove_readings(book_id: int, body: RemoveReadings) -> Dict:
        return after(book_id, actions.remove_readings(library, book_id, body.sample_ids, body.engine))

    @app.post("/api/books/{book_id}/actions/label-samples", dependencies=auth)
    def a_label_samples(book_id: int, body: LabelSamples) -> Dict:
        return after(book_id, actions.label_samples(library, book_id, body.sample_ids, body.text))

    @app.post("/api/books/{book_id}/actions/status", dependencies=auth)
    def a_status(book_id: int, body: Status) -> Dict:
        return after(book_id, actions.set_status(library, book_id, body.group_id, body.reviewed, body.locked))

    @app.post("/api/books/{book_id}/actions/delete", dependencies=auth)
    def a_delete(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.delete_samples(library, book_id, body.sample_ids))

    @app.post("/api/books/{book_id}/actions/restore", dependencies=auth)
    def a_restore(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.restore_samples(library, book_id, body.sample_ids))

    # ---- fixing cuts and adding samples (C5f) ----------------------------------------------------------
    @app.post("/api/books/{book_id}/samples/crop", dependencies=auth)
    def s_crop(book_id: int, body: Crop) -> Dict:
        return after(book_id, manual.crop_sample(library, book_id, body.page_id, tuple(body.box)))

    @app.post("/api/books/{book_id}/samples/join", dependencies=auth)
    def s_join(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, manual.join_samples(library, book_id, body.sample_ids))

    @app.post("/api/books/{book_id}/samples/split", dependencies=auth)
    def s_split(book_id: int, body: Split) -> Dict:
        return after(book_id, manual.split_sample(library, book_id, body.sample_id, body.x))

    @app.post("/api/books/{book_id}/samples/upload", dependencies=auth)
    def s_upload(book_id: int, body: Upload) -> Dict:
        return after(book_id, manual.upload_sample(library, book_id, body.filename, body.data))

    @app.post("/api/books/{book_id}/undo", dependencies=auth)
    def a_undo(book_id: int) -> Dict:
        return after(book_id, actions.undo(library, book_id))

    @app.post("/api/books/{book_id}/redo", dependencies=auth)
    def a_redo(book_id: int) -> Dict:
        return after(book_id, actions.redo(library, book_id))

    @app.get("/api/books/{book_id}/history", dependencies=auth)
    def a_history(book_id: int, limit: int = Query(50, le=MAX_PAGE)) -> List[Dict]:
        library.get_book(book_id)
        return actions.history(library, book_id, limit)

    # ---- labels ------------------------------------------------------------------------------------
    @app.get("/api/label", dependencies=auth)
    def label(text: str, book_id: Optional[int] = None) -> Dict:
        cfg = library.book_config(library.get_book(book_id)) if book_id else Config()
        info = describe(text, mapping_for(cfg), words=True)
        if info["ok"] and book_id:
            with library.session() as s:
                same = s.scalars(select(LetterGroup).where(LetterGroup.book_id == book_id,
                                                           LetterGroup.label_dev == info["devanagari"])
                                 .order_by(LetterGroup.code)).all()
                info["used_by"] = [{"id": g.id, "code": g.code, "locked": g.locked,
                                    "samples": s.scalar(select(func.count()).select_from(Sample).where(
                                        Sample.group_id == g.id, Sample.deleted.is_(False)))} for g in same]
        return info

    # ---- files ---------------------------------------------------------------------------------------
    @app.get("/files/books/{book_id}/{path:path}", dependencies=auth)
    def book_file(book_id: int, path: str):
        book = library.get_book(book_id)
        root = library.book_dir(book).resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() != ".png":
            raise HTTPException(404, "No such file in this book.")
        return FileResponse(target, headers={"Cache-Control": "no-cache"})

    @app.get("/files/pages/{page_id}", dependencies=auth)
    def page_file(page_id: int):
        with library.session() as s:
            p = s.get(Page, page_id)
            if p is None:
                raise HTTPException(404, f"No page with id {page_id}.")
            book = s.get(Book, p.book_id)
            target = library.page_path(book, p)
        if not target.is_file():
            raise HTTPException(404, f"The page image {p.file} is missing.")
        return FileResponse(target)

    @app.get("/files/samples/{sample_id}/context", dependencies=auth)
    def sample_context(sample_id: int):
        """The sample on its line with 4 neighbours on each side (shown when one sample is selected)."""
        return Response(manual.line_context(library, sample_id), media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get("/api/version")
    def version() -> Dict:
        return {"version": __version__}

    # ---- the app itself (C5d) -------------------------------------------------------------------------
    @app.get("/api/app", dependencies=auth)
    def app_info() -> Dict:
        return {"version": __version__, "library": str(library.root), "mode": context.mode,
                "can_pick_folder": context.pick_folder is not None}

    @app.post("/api/app/library", dependencies=auth)
    def choose_library(body: LibraryChoice) -> Dict:
        path = Path(body.path).expanduser()
        if path.exists() and not path.is_dir():
            raise HTTPException(400, f"Not a folder: {path}")
        save_settings({"library": str(path)}, context.settings_file)
        return {"library": str(path), "restart_needed": path.resolve() != library.root.resolve()}

    @app.post("/api/app/pick-folder", dependencies=auth)
    def pick_folder() -> Dict:
        if context.pick_folder is None:
            raise HTTPException(501, "No folder dialog in the browser; type the folder path.")
        return {"path": context.pick_folder()}

    @app.post("/api/app/open-help", dependencies=auth)
    def open_help(body: HelpPage, request: Request) -> Dict:
        """In the app window, help opens in the web browser (the window has no tabs)."""
        if not body.page.replace("-", "").replace(".", "").isalnum():
            raise HTTPException(400, "Not a help page.")
        url = str(request.base_url) + f"help/{body.page}"
        import webbrowser
        webbrowser.open(url)
        return {"opened": url}

    @app.post("/api/app/open-folder", dependencies=auth)
    def open_folder(body: FolderPath) -> Dict:
        path = Path(body.path).expanduser()
        if not path.is_dir():
            raise HTTPException(404, f"No such folder: {path}")
        context.open_folder(path)
        return {"opened": str(path)}

    @app.patch("/api/books/{book_id}/settings", dependencies=auth)
    def book_settings(book_id: int, body: BookSettings) -> Dict:
        try:
            cfg = load_config(None, **body.settings) if body.settings else Config()
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Settings: {e}")
        library.set_book_config(book_id, cfg)
        return get_book(book_id)

    # ---- the screen ------------------------------------------------------------------------------------
    index = context.static_dir / "index.html"

    @app.get("/", include_in_schema=False)
    def screen():
        if not index.is_file():
            return HTMLResponse("<h1>The screen is not built</h1><p>Run <code>npm run build</code> in frontend/.</p>",
                                status_code=503)
        html = index.read_text(encoding="utf-8")
        tag = f"<script>window.__TOKEN__ = {json.dumps(token)};</script>"
        return HTMLResponse(html.replace("</head>", tag + "</head>", 1),
                            headers={"Cache-Control": "no-store"})

    if (context.static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=context.static_dir / "assets"), name="assets")
    if (context.static_dir / "help").is_dir():
        # help pages (copied from docs/help/ by the screen's build); no data, so no token needed
        app.mount("/help", StaticFiles(directory=context.static_dir / "help", html=True), name="help")

    return app
