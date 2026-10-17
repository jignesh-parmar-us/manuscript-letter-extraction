"""The backend API of the review app (C5c), a FastAPI application.

`create_app(library, token)` returns the app. It listens on 127.0.0.1 only unless started with --host (see main.py,
C5d). Every request must carry the session token, created when the app starts: in the `X-Token`
header, or as `?token=` for images (an <img> tag cannot send headers). Other web pages open in the
same browser therefore cannot use the API.

Routes (all JSON unless noted). Since C20 a row is a dataset or a book: what only a dataset has (capture, groups,
review actions, the letter checker, export) is under /api/datasets/{id}/... (404 for a book); reading is under
/api/books/{id}/...; what both have (the row, pages, page-problems, recut, undo / redo / history, label-samples,
delete / restore, crop / join / split, settings) answers under both prefixes. Below, {D} is /api/datasets/{id}
and {B} /api/books/{id}; the older lines say /api/books/{id} for both.
  rows (C20) GET/POST /api/datasets, GET/POST /api/books (a new book: `dataset_id`, a first dataset to learn from),
             GET/PATCH/DELETE {B} or {D}; a row carries `kind`, `datasets` (a book's, C23), `used_by` (a dataset's);
  setup(C23) GET /api/books/{id}/reading-setup (its reading model: datasets, other datasets, reader, measures),
             PUT /api/books/{id}/datasets {"dataset_ids"} (the datasets its reading model learns from);
             POST /api/app/uploads (the uploads folder; C26: the pages uploaded before move with it, a job)
  moves(C26) GET /api/app carries `page_move` (the report of the page images moved into the uploads folder at the
             start, until seen), POST /api/app/page-move/seen
  pages(C22) GET {B}/page-list (the page manager: order, excluded, not prepared yet, what is on each page),
             POST {B}/page-list/exclude {"file", "excluded", "force"}, POST {B}/page-list/delete {"file", "force"},
             POST {B}/pages/{page_id}/move {"by"}, GET /files/rows/{id}/thumb?name= (also under {D});
             GET {B}/pages hides excluded pages unless ?excluded=true
  uploads    POST {D}/upload?name= | {B}/upload?name= (C21; one page image or PDF, the file as the body; a PDF
             answers with a job turning it into page images), POST {D}/copy-folder {"path"} (a job: a folder's
             images copied into the uploads folder); deleting a row deletes its uploads
  books      POST {D}/folder (the Training Data page images), GET /api/books/{id}/page-problems
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
             their letters were made so; POST /api/books/{id}/actions/variants {"group_id"} (more letters for
             one group), POST /api/books/{id}/top-up (a job: every small group)
  export     POST /api/books/{id}/export (a job), POST /api/app/open-folder   (C5g)
  fonts (T1) GET /api/fonts (the library's fonts for the text screens), POST /api/fonts/upload?name= (a .ttf/.otf
             as the body; an old-style font is refused), GET /api/fonts/fontmaker (Font Maker's built fonts),
             POST /api/fonts/fontmaker {"project"}, PATCH /api/fonts/{id} {"size"} (A- / A+), DELETE /api/fonts/{id}, GET /files/fonts/{id} (the font file);
             GET /files/texts/{id}?format=docx&font={id} sets (and embeds) that font in the Word file
  app (C5d)  GET /api/app, POST /api/app/library, POST /api/app/pick-folder,
             PATCH /api/books/{id}/settings; GET / serves the built screen with the token in it;
             GET /help/<page> the help pages (no token), POST /api/app/open-help (window mode)
"""
from __future__ import annotations

import dataclasses
import json
import os
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
from .db import BOOK, DATASET, GENERATED, Book, LetterGroup, Line, Page, Sample
from .jobs import Jobs
from .library import BookHasReviewError, Library, LibraryError, NotFound
from .schemas import (DatasetChoice, PageExclude, PageFile, PageMove, AcceptSuggestions, ConfirmSamples, LineSearchRequest, BookCreate, BookUpdate, BookSettings, Crop, ExportRequest, FolderPath, Force,
                      ConvertRequest, PagePart, Proofread, ReadSource, ReaderChoice, TrainRequest, WordListImport, WordListUse, LineTruthText, WholeLineEdit,
                      FontMakerFont, FontSize, GroupRef, HelpPage, Label, LabelSamples, LibraryChoice, Merge, Move, RejectSuggestion,
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
    from .main import AppContext, save_settings, uploads_dir
    context = context or AppContext()
    app = FastAPI(title="Manuscript Letter Extraction", version=__version__)
    jobs = Jobs(library)
    app.state.library, app.state.jobs, app.state.token = library, jobs, token

    def check_token(x_token: Optional[str] = Header(default=None), q_token: Optional[str] = Query(default=None,
                                                                                                    alias="token")):
        if token and (x_token or q_token) != token:
            raise HTTPException(status_code=401, detail="Missing or wrong session token.")

    auth = [Depends(check_token)]

    # ---- datasets and books (C20) ----------------------------------------------------------------------
    # Routes of what only a dataset has (capture, groups, review actions, letter checker, export) are under
    # /api/datasets/{id}; those of reading under /api/books/{id} (a dataset has no Read Book pages: they answer
    # with nothing). What both have (the row, its pages, undo, cut fixes, settings) answers under both.
    def _dataset_only(book_id: int) -> None:
        with library.session() as s:
            b = s.get(Book, book_id)
            if b is None or b.kind != DATASET:
                raise HTTPException(404, f"No dataset with id {book_id}.")

    ds = auth + [Depends(_dataset_only)]

    def both(method: str, path: str, **kw):
        """Register a route of a row under both /api/books and /api/datasets (`path` starts at /{book_id})."""
        def deco(f):
            route = getattr(app, method)
            route("/api/datasets" + path, **kw)(f)
            return route("/api/books" + path, **kw)(f)
        return deco

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
        return [_book_json(b) for b in library.list_books(BOOK)]

    @app.get("/api/datasets", dependencies=auth)
    def list_datasets() -> List[Dict]:
        return [_book_json(b) for b in library.list_books(DATASET)]

    def _create(body: BookCreate, kind: str) -> Dict:
        try:
            cfg = load_config(None, **body.settings) if body.settings else None
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Settings: {e}")
        book = library.create_book(body.name, Path(body.input_dir) if body.input_dir.strip() else None, cfg,
                                   body.writing, kind=kind, dataset_id=body.dataset_id)
        return get_book(book.id)

    @app.post("/api/books", dependencies=auth, status_code=201)
    def create_book(body: BookCreate) -> Dict:
        return _create(body, BOOK)

    @app.post("/api/datasets", dependencies=auth, status_code=201)
    def create_dataset(body: BookCreate) -> Dict:
        return _create(body, DATASET)

    @app.post("/api/datasets/{book_id}/folder", dependencies=ds)
    def input_folder(book_id: int, body: FolderPath) -> Dict:
        library.set_input_folder(book_id, Path(body.path))
        return get_book(book_id)

    # ---- fonts to show the text in (T1, docs/CUSTOM_FONT_PLAN.md) -----------------------------------------
    from .fonts import FontError, FontNotFound, Fonts
    fonts = Fonts(library.root)

    def font_or_404(run):
        try:
            return run()
        except FontNotFound:
            raise HTTPException(404, "No such font.")
        except FontError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/fonts", dependencies=auth)
    def list_fonts() -> List[Dict]:
        return fonts.list()

    @app.post("/api/fonts/upload", dependencies=auth)
    async def upload_font(request: Request, name: str = Query(...)) -> Dict:
        data = await request.body()
        return font_or_404(lambda: fonts.add_upload(name, data))

    @app.get("/api/fonts/fontmaker", dependencies=auth)
    def fontmaker_fonts() -> List[Dict]:
        return fonts.fontmaker_fonts()

    @app.post("/api/fonts/fontmaker", dependencies=auth)
    def add_fontmaker_font(body: FontMakerFont) -> Dict:
        return font_or_404(lambda: fonts.add_fontmaker(body.project))

    @app.patch("/api/fonts/{font_id}", dependencies=auth)
    def set_font_size(font_id: str, body: FontSize) -> Dict:
        return font_or_404(lambda: fonts.set_size(font_id, body.size))

    @app.delete("/api/fonts/{font_id}", dependencies=auth, status_code=204)
    def remove_font(font_id: str) -> None:
        font_or_404(lambda: fonts.remove(font_id))

    @app.get("/files/fonts/{font_id}", dependencies=auth)
    def font_file(font_id: str):
        path = font_or_404(lambda: fonts.path(font_id))
        return FileResponse(path, media_type="font/otf" if path.suffix == ".otf" else "font/ttf")

    # ---- uploads (C21) -----------------------------------------------------------------------------------
    def uploads() -> Path:
        return uploads_dir(library.root, context.settings_file)

    async def _upload(book_id: int, kind: str, request: Request, name: str) -> Dict:
        """One file per request, the file itself as the body (no form parsing needed). An image is kept in the
        row's upload folder; a PDF too, and then a job turns it into page images (`job` in the answer)."""
        with library.session() as s:
            b = s.get(Book, book_id)
            if b is None or b.kind != kind:
                raise HTTPException(404, f"No {'dataset' if kind == DATASET else 'book'} with id {book_id}.")
        target = library.upload_target(book_id, name, uploads())
        part = target.with_name(f".{target.name}.part")
        try:
            with open(part, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
            if part.stat().st_size == 0:
                raise HTTPException(400, f"'{target.name}' is empty.")
            part.rename(target)
        finally:
            part.unlink(missing_ok=True)
        if target.suffix.lower() == ".pdf":
            return {"job": jobs.uploaded_pdf(book_id, target, uploads()).as_dict(), "book": None}
        library.use_upload_folder(book_id, uploads())
        return {"job": None, "book": get_book(book_id)}

    @app.post("/api/datasets/{book_id}/upload", dependencies=auth)
    async def upload_dataset_page(book_id: int, request: Request, name: str = Query(...)) -> Dict:
        return await _upload(book_id, DATASET, request, name)

    @app.post("/api/books/{book_id}/upload", dependencies=auth)
    async def upload_book_page(book_id: int, request: Request, name: str = Query(...)) -> Dict:
        return await _upload(book_id, BOOK, request, name)

    @app.post("/api/datasets/{book_id}/copy-folder", dependencies=ds, status_code=202)
    def copy_folder(book_id: int, body: FolderPath) -> Dict:
        return jobs.copy_pages(book_id, body.path, uploads()).as_dict()

    # ---- the page manager (C22) -------------------------------------------------------------------------
    def _no_job(book_id: int) -> None:
        if jobs.running_for(book_id):
            raise HTTPException(409, "A job is running for this book; change its pages when it has finished.")

    @both("get", "/{book_id}/page-list", dependencies=auth)
    def page_list(book_id: int) -> Dict:
        """The pages in order (also excluded ones and image files not prepared yet), each with its thumbnail."""
        from urllib.parse import quote
        from .pages import page_list as listing
        got = listing(library, book_id, uploads())
        for p in got["pages"]:
            p["thumb"] = f"/files/rows/{book_id}/thumb?name={quote(p['file'])}&token={token}"
        return got

    @both("post", "/{book_id}/page-list/exclude", dependencies=auth)
    def exclude_page(book_id: int, body: PageExclude) -> Dict:
        from .pages import set_excluded
        _no_job(book_id)
        return set_excluded(library, book_id, body.file, body.excluded, body.force)

    @both("post", "/{book_id}/page-list/delete", dependencies=auth)
    def delete_page(book_id: int, body: PageFile) -> Dict:
        from .pages import delete_page as remove
        _no_job(book_id)
        return remove(library, book_id, body.file, uploads(), body.force)

    @both("post", "/{book_id}/pages/{page_id}/move", dependencies=auth)
    def move_page(book_id: int, page_id: int, body: PageMove) -> Dict:
        from .pages import move_page as move
        _no_job(book_id)
        return move(library, book_id, page_id, body.by)

    @app.get("/files/rows/{book_id}/thumb", dependencies=auth)
    def page_thumb(book_id: int, name: str = Query(...)):
        from .pages import thumbnail
        return FileResponse(thumbnail(library, book_id, name), headers={"Cache-Control": "max-age=3600"})

    @both("get", "/{book_id}", dependencies=auth)
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

    @both("patch", "/{book_id}", dependencies=auth)
    def update_book(book_id: int, body: BookUpdate) -> Dict:
        if body.name is not None:
            library.rename_book(book_id, body.name)
        if body.writing is not None:
            library.set_book_writing(book_id, body.writing)
        return get_book(book_id)

    @both("delete", "/{book_id}", dependencies=auth, status_code=204)
    def delete_book(book_id: int) -> None:
        if jobs.running_for(book_id):
            raise HTTPException(409, "A capture is running for this book.")
        library.delete_book(book_id, uploads())

    @both("get", "/{book_id}/page-problems", dependencies=auth)
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
        """The book's line-search reader (what it was trained on, or null), its last measure and its last quick
        measure (2 of the 4 folds, for screening only), each null when there is none."""
        from .linesearch import last_measure, line_reader_info
        return {"reader": line_reader_info(library, book_id), "measure": last_measure(library, book_id),
                "quick_measure": last_measure(library, book_id, quick=True)}

    # ---- Reading setup (C23) -------------------------------------------------------------------------
    @app.get("/api/books/{book_id}/reading-setup", dependencies=auth)
    def reading_setup(book_id: int) -> Dict:
        """The book's reading model: the datasets it learns from (and the other datasets, to add), what its reader
        was trained on (`changed`: out of date) and the last measures."""
        from .db import ReadingModel
        from .linesearch import last_measure, line_reader_info
        book = library.get_book(book_id)
        library.need_kind(book, BOOK, "a reading setup")
        used = library.training_sources(book)
        rows = {b["id"]: _book_json(b) for b in library.list_books(DATASET)}
        with library.session() as s:
            m = s.get(ReadingModel, book.reading_model_id) if book.reading_model_id else None
            model = {"id": m.id, "name": m.name, "folder": str(library.root / "models" / m.folder)} if m else None
        return {"model": model, "writing": book.writing,
                "datasets": [rows[d] for d in used if d in rows],
                "others": [r for d, r in rows.items() if d not in used],
                "reader": line_reader_info(library, book_id), "measure": last_measure(library, book_id),
                "quick_measure": last_measure(library, book_id, quick=True)}

    @app.put("/api/books/{book_id}/datasets", dependencies=auth)
    def choose_datasets(book_id: int, body: DatasetChoice) -> Dict:
        if jobs.running_for(book_id):
            raise HTTPException(409, "A job is running for this book; choose its datasets when it has finished.")
        library.set_book_datasets(book_id, body.dataset_ids)
        return reading_setup(book_id)

    @app.post("/api/books/{book_id}/line-search/train", dependencies=auth, status_code=202)
    def line_search_train(book_id: int) -> Dict:
        """Train the line search reader again on the reviewed letters and the checked lines (a job)."""
        return jobs.line_search_train(book_id).as_dict()

    @app.post("/api/books/{book_id}/line-search/measure", dependencies=auth, status_code=202)
    def line_search_measure(book_id: int, quick: bool = Query(False)) -> Dict:
        """Score the line search fold-fair on the checked lines (a job); `quick`: 2 of the 4 folds, for screening."""
        return jobs.line_search_measure(book_id, quick).as_dict()

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
                      readers: str = Query("both", pattern="^(both|tesseract|lines|lines_lm|search)$"),
                      page_ids: Optional[str] = Query(None, pattern=r"^\d+(,\d+)*$"),
                      font: Optional[str] = None, scale: float = Query(1.0, ge=0.5, le=2.0)):
        """The text of one page, of the pages `page_ids` (the ticked pages, comma-separated; C19) or of every
        converted page of a part, as .txt (UTF-8) or Word. `font` (T3): a Word file in that font of the
        library's fonts, embedded when the font allows it (a .txt has no font); `scale`: that font's size against
        the normal fonts' (measured by the screen), applied to the text's font size."""
        from urllib.parse import quote
        from ..mapping import mapping_for
        from ..ocr.docx import write_docx
        from .texts import book_page_texts, marked_lines
        book = library.get_book(book_id)
        cfg = library.book_config(book)
        mapping = mapping_for(cfg)
        ids = [int(i) for i in page_ids.split(",")] if page_ids else None
        if ids and len(ids) == 1 and not page_id:          # one ticked page: as that page alone
            page_id, ids = ids[0], None
        if readers in ("lines", "lines_lm", "search"):   # lines read whole by Tesseract (+ the language
            from .wholelines import whole_line_texts      # model), or by the line search (our reader)
            rows = whole_line_texts(library, book_id, part, page_id, "search" if readers == "search" else "tesseract",
                                    page_ids=ids)
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
            rows = book_page_texts(library, book_id, part, page_id, page_ids=ids)
            if not rows:
                raise HTTPException(404, "Nothing converted yet.")
            pages = [(f"{p.number or i} · {p.file}" if not page_id else "",
                      marked_lines(t["lines"], marker or cfg.uncertain_marker, script, mapping, readers))
                     for i, (p, t) in enumerate(rows, 1)]
        name = Path(rows[0][0].file).stem if page_id else book.name
        if format == "docx":
            family, embed = font_or_404(lambda: fonts.for_word(font)) if font else (None, None)
            data = write_docx(pages, family, embed, scale if font else 1.0)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            parts = [("" if not heading else f"=== {heading} ===\n") + "\n".join(lines) for heading, lines in pages]
            data = ("\n\n".join(parts) + "\n").encode("utf-8")
            media = "text/plain; charset=utf-8"
        disposition = f"attachment; filename*=UTF-8''{quote(name)}.{format}"
        return Response(data, media_type=media, headers={"Content-Disposition": disposition})

    @app.get("/files/page-images/{book_id}", dependencies=auth)
    def download_page_images(book_id: int, page_id: Optional[int] = None,
                             part: str = Query("read", pattern="^(training|read)$"),
                             page_ids: Optional[str] = Query(None, pattern=r"^\d+(,\d+)*$")):
        """The page images of one page, of the pages `page_ids` (comma-separated; C19) or of every page of a
        part, as one PDF (a page for each image)."""
        import tempfile
        from urllib.parse import quote
        from starlette.background import BackgroundTask
        from ..ocr.pdf import images_pdf
        book = library.get_book(book_id)
        with library.session() as s:
            q = select(Page).where(Page.book_id == book_id, Page.part == part)
            if page_id:
                q = q.where(Page.id == page_id)
            else:
                q = q.where(Page.excluded.is_(False))                  # C22
            if page_ids:
                q = q.where(Page.id.in_([int(i) for i in page_ids.split(",")]))
            rows = s.scalars(q.order_by(Page.number, Page.id)).all()
            files = [library.page_path(book, p) for p in rows]
        if not files:
            raise HTTPException(404, "No pages.")
        missing = [f.name for f in files if not f.is_file()]
        if missing:
            raise HTTPException(404, f"The page image {missing[0]} is missing.")
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            images_pdf(files, Path(tmp), dpi=library.book_config(book).pdf_dpi)
        except Exception:
            os.unlink(tmp)
            raise
        name = f"{files[0].stem if page_id or len(files) == 1 else book.name} - page images.pdf"
        return FileResponse(tmp, media_type="application/pdf", background=BackgroundTask(os.unlink, tmp),
                            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

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

    @app.post("/api/datasets/{book_id}/train", dependencies=ds, status_code=202)
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

    @app.post("/api/datasets/{book_id}/reader", dependencies=ds, status_code=202)
    def use_reader(book_id: int, body: ReaderChoice) -> Dict:
        return jobs.use_reader(book_id, body.reader_id).as_dict()

    @app.post("/api/datasets/{book_id}/check/confirm", dependencies=ds)
    def check_confirm(book_id: int, body: ConfirmSamples) -> Dict:
        """Letters that are no mix-up (or are again, `ok` false): they leave Check these and the highlights."""
        from .readers import confirm_samples
        return {"confirmed": confirm_samples(library, book_id, body.sample_ids, body.ok)}

    @app.get("/api/datasets/{book_id}/check", dependencies=ds)
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
    @app.post("/api/datasets/{book_id}/capture", dependencies=ds, status_code=202)
    def capture(book_id: int, body: Force = Force()) -> Dict:
        return jobs.capture(book_id, force=body.force).as_dict()

    @app.post("/api/datasets/{book_id}/add-pages", dependencies=ds, status_code=202)
    def add_pages(book_id: int) -> Dict:
        return jobs.add_pages(book_id).as_dict()

    @both("post", "/{book_id}/pages/{page_id}/recut", dependencies=auth, status_code=202)
    def recut(book_id: int, page_id: int, body: Force = Force()) -> Dict:
        return jobs.recut_page(book_id, page_id, force=body.force).as_dict()

    def tesseract_setting() -> str:
        from .main import load_settings
        return str(load_settings(context.settings_file).get("tesseract_path", ""))   # app setting, not per book

    @app.post("/api/datasets/{book_id}/suggest", dependencies=ds, status_code=202)
    def suggest(book_id: int, body: SuggestRequest = SuggestRequest()) -> Dict:
        return jobs.suggest(book_id, body.engine, tesseract_setting(), body.books).as_dict()

    @app.get("/api/datasets/{book_id}/reference-books", dependencies=ds)
    def ref_books(book_id: int) -> List[Dict]:
        """The other books with labelled groups, for suggestions from labelled books (C13)."""
        return reference_books(library, book_id)

    @app.post("/api/datasets/{book_id}/fix-cuts", dependencies=ds, status_code=202)
    def fix_cuts(book_id: int) -> Dict:
        book = library.get_book(book_id)
        if book.writing != "printed":
            raise HTTPException(400, "Fixing cuts with Tesseract is for printed books.")
        return jobs.fix_cuts(book_id).as_dict()

    @app.post("/api/datasets/{book_id}/fix-bars", dependencies=ds, status_code=202)
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

    @app.post("/api/datasets/{book_id}/export", dependencies=ds, status_code=202)
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
    @both("get", "/{book_id}/pages", dependencies=auth)
    def pages(book_id: int, part: str = Query("training", pattern="^(training|read)$"),
              excluded: bool = False) -> List[Dict]:
        """The pages of a part in order; excluded pages (C22) only with `excluded=true`."""
        with library.session() as s:
            book_or_404(s, book_id)
            out = []
            q = select(Page).where(Page.book_id == book_id, Page.part == part)
            if not excluded:
                q = q.where(Page.excluded.is_(False))
            for p in s.scalars(q.order_by(Page.number, Page.id)):
                n = s.scalar(select(func.count(Sample.id)).where(Sample.page_id == p.id, Sample.deleted.is_(False)))
                out.append({"id": p.id, "file": p.file, "width": p.width, "height": p.height, "status": p.status,
                            "message": p.message, "lines": len(p.lines), "samples": n, "part": p.part,
                            "number": p.number, "excluded": p.excluded,
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

    @app.post("/api/datasets/{book_id}/generate-letters", dependencies=ds, status_code=202)
    def generate_letters(book_id: int) -> Dict:
        book = library.get_book(book_id)
        if book.writing != "printed":
            raise HTTPException(400, "Generating missing letters is for printed books for now.")
        return jobs.generate_letters(book_id).as_dict()

    @app.post("/api/datasets/{book_id}/top-up", dependencies=ds, status_code=202)
    def top_up(book_id: int) -> Dict:
        library.get_book(book_id)
        return jobs.top_up(book_id).as_dict()

    @app.get("/api/datasets/{book_id}/groups", dependencies=ds)
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

    @app.get("/api/datasets/{book_id}/suggestion-accuracy", dependencies=ds)
    def accuracy(book_id: int, engine: Optional[str] = None) -> Dict:
        with library.session() as s:
            book = book_or_404(s, book_id)
            return suggestion_accuracy(s, book, library.book_config(book), engine)

    @app.get("/api/datasets/{book_id}/unsure", dependencies=ds)
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

    @app.post("/api/datasets/{book_id}/actions/move", dependencies=ds)
    def a_move(book_id: int, body: Move) -> Dict:
        return after(book_id, actions.move_samples(library, book_id, body.sample_ids, body.group_id))

    @app.post("/api/datasets/{book_id}/actions/new-group", dependencies=ds)
    def a_new_group(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.new_group(library, book_id, body.sample_ids))

    @app.post("/api/datasets/{book_id}/actions/merge", dependencies=ds)
    def a_merge(book_id: int, body: Merge) -> Dict:
        return after(book_id, actions.merge_groups(library, book_id, body.target_id, body.source_ids))

    @app.post("/api/datasets/{book_id}/actions/dissolve", dependencies=ds)
    def a_dissolve(book_id: int, body: GroupRef) -> Dict:
        return after(book_id, actions.dissolve_group(library, book_id, body.group_id))

    @app.post("/api/datasets/{book_id}/actions/label", dependencies=ds)
    def a_label(book_id: int, body: Label) -> Dict:
        return after(book_id, actions.set_label(library, book_id, body.group_id, body.text))

    @app.post("/api/datasets/{book_id}/actions/accept-suggestions", dependencies=ds)
    def a_accept(book_id: int, body: AcceptSuggestions) -> Dict:
        return after(book_id, actions.accept_suggestions(library, book_id, [i.model_dump() for i in body.items]))

    @app.post("/api/datasets/{book_id}/actions/reject-suggestion", dependencies=ds)
    def a_reject(book_id: int, body: RejectSuggestion) -> Dict:
        return after(book_id, actions.reject_suggestion(library, book_id, body.group_id, body.label_dev))

    @app.post("/api/datasets/{book_id}/actions/split-mixed", dependencies=ds)
    def a_split_mixed(book_id: int) -> Dict:
        library.get_book(book_id)
        return after(book_id, actions.split_mixed(library, book_id))

    @app.post("/api/datasets/{book_id}/actions/remove-readings", dependencies=ds)
    def a_remove_readings(book_id: int, body: RemoveReadings) -> Dict:
        return after(book_id, actions.remove_readings(library, book_id, body.sample_ids, body.engine))

    @both("post", "/{book_id}/actions/label-samples", dependencies=auth)
    def a_label_samples(book_id: int, body: LabelSamples) -> Dict:
        return after(book_id, actions.label_samples(library, book_id, body.sample_ids, body.text))

    @app.post("/api/datasets/{book_id}/actions/status", dependencies=ds)
    def a_status(book_id: int, body: Status) -> Dict:
        return after(book_id, actions.set_status(library, book_id, body.group_id, body.reviewed, body.locked))

    @app.post("/api/datasets/{book_id}/actions/variants", dependencies=ds)
    def a_variants(book_id: int, body: GroupRef) -> Dict:
        from .generate import variants
        return after(book_id, variants(library, book_id, body.group_id))

    @both("post", "/{book_id}/actions/delete", dependencies=auth)
    def a_delete(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.delete_samples(library, book_id, body.sample_ids))

    @both("post", "/{book_id}/actions/restore", dependencies=auth)
    def a_restore(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, actions.restore_samples(library, book_id, body.sample_ids))

    # ---- fixing cuts and adding samples (C5f) ----------------------------------------------------------
    @both("post", "/{book_id}/samples/crop", dependencies=auth)
    def s_crop(book_id: int, body: Crop) -> Dict:
        return after(book_id, manual.crop_sample(library, book_id, body.page_id, tuple(body.box)))

    @both("post", "/{book_id}/samples/join", dependencies=auth)
    def s_join(book_id: int, body: SampleIds) -> Dict:
        return after(book_id, manual.join_samples(library, book_id, body.sample_ids))

    @both("post", "/{book_id}/samples/split", dependencies=auth)
    def s_split(book_id: int, body: Split) -> Dict:
        return after(book_id, manual.split_sample(library, book_id, body.sample_id, body.x))

    @app.post("/api/datasets/{book_id}/samples/upload", dependencies=ds)
    def s_upload(book_id: int, body: Upload) -> Dict:
        return after(book_id, manual.upload_sample(library, book_id, body.filename, body.data))

    @both("post", "/{book_id}/undo", dependencies=auth)
    def a_undo(book_id: int) -> Dict:
        return after(book_id, actions.undo(library, book_id))

    @both("post", "/{book_id}/redo", dependencies=auth)
    def a_redo(book_id: int) -> Dict:
        return after(book_id, actions.redo(library, book_id))

    @both("get", "/{book_id}/history", dependencies=auth)
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
        from .move import notice
        return {"version": __version__, "library": str(library.root), "mode": context.mode,
                "can_pick_folder": context.pick_folder is not None,
                "uploads": str(uploads_dir(library.root, context.settings_file)),
                "page_move": notice(library)}

    @app.post("/api/app/page-move/seen", dependencies=auth)
    def page_move_seen() -> Dict:
        """The notice of the page images moved into the uploads folder (C26) was read: not shown again."""
        from .move import notice_seen
        notice_seen(library)
        return {"ok": True}

    @app.post("/api/app/uploads", dependencies=auth)
    def choose_uploads(body: FolderPath) -> Dict:
        """The uploads folder (C20): where uploads go. Since C26 the pages uploaded before move with it (a job:
        copied, checked, the rows switched; the setting is stored when that worked). `job` is None when there was
        nothing to move."""
        path = Path(body.path).expanduser()
        if path.exists() and not path.is_dir():
            raise HTTPException(400, f"Not a folder: {path}")
        old = uploads_dir(library.root, context.settings_file)

        def save() -> None:
            save_settings({"uploads": str(path)}, context.settings_file)
        if path.resolve() == old.resolve() or not any(p.is_dir() for p in (old / "datasets", old / "books")):
            save()
            return {"uploads": str(path), "job": None}
        return {"uploads": str(path), "job": jobs.move_uploads(old, path, save).as_dict()}

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

    @both("patch", "/{book_id}/settings", dependencies=auth)
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
