"""The backend API of the review app (C5c), a FastAPI application.

`create_app(library, token)` returns the app. It is meant to listen on 127.0.0.1 only (see main.py,
C5d). Every request must carry the session token, created when the app starts: in the `X-Token`
header, or as `?token=` for images (an <img> tag cannot send headers). Other web pages open in the
same browser therefore cannot use the API.

Routes (all JSON unless noted):
  books      GET/POST /api/books, GET/PATCH/DELETE /api/books/{id}, GET /api/books/{id}/page-problems
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
             POST /api/books/{id}/actions/split-mixed (C12d),
             POST /api/books/{id}/undo | /redo, GET /api/books/{id}/history
  labels     GET /api/label?text=...&book_id=...   (with a book: `used_by`, the groups with that label)
  files      GET /files/books/{id}/{path} (letter, mask and line images), GET /files/pages/{page_id}
             (the input page image)
  samples    POST /api/books/{id}/samples/{crop|join|split|upload}   (C5f)
  export     POST /api/books/{id}/export (a job), POST /api/app/open-folder   (C5g)
  app (C5d)  GET /api/app, POST /api/app/library, POST /api/app/pick-folder,
             PATCH /api/books/{id}/settings; GET / serves the built screen with the token in it
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from .. import __version__
from ..config import Config, load_config
from ..mapping import describe, mapping_for
from . import actions, samples as manual
from .centres import suggestions
from .db import Book, LetterGroup, Line, Page, Sample
from .jobs import Jobs
from .library import BookHasReviewError, Library, LibraryError, NotFound
from .schemas import (AcceptSuggestions, BookCreate, BookUpdate, BookSettings, Crop, ExportRequest, FolderPath, Force,
                      GroupRef, Label, LabelSamples, LibraryChoice, Merge, Move, RejectSuggestion, SampleIds, Split,
                      Status, SuggestRequest, Upload)
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
            "image": f"/files/books/{book_id}/{smp.image}?token={token}"}


def _group_json(s, g: LetterGroup, token: str, ocr: Optional[Dict] = None) -> Dict:
    """`ocr`: the group's entry of suggest.group_readings (suggestion and most common readings)."""
    mem = s.scalars(select(Sample).where(Sample.group_id == g.id, Sample.deleted.is_(False))
                    .order_by(Sample.distance)).all()
    red = sum(m.ink == "red" for m in mem)
    dists = [m.distance for m in mem if m.distance is not None]
    return {"id": g.id, "code": g.code, "kind": g.kind, "label_dev": g.label_dev, "label_guj": g.label_guj,
            "status": g.status, "locked": g.locked, "samples": len(mem), "red": red, "black": len(mem) - red,
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
        book = library.create_book(body.name, Path(body.input_dir).expanduser(), cfg, body.writing)
        return get_book(book.id)

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
    def page_problems(book_id: int) -> List[Dict]:
        return library.check_pages(book_id)

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
    def pages(book_id: int) -> List[Dict]:
        with library.session() as s:
            book_or_404(s, book_id)
            out = []
            for p in s.scalars(select(Page).where(Page.book_id == book_id).order_by(Page.id)):
                n = s.scalar(select(func.count(Sample.id)).where(Sample.page_id == p.id, Sample.deleted.is_(False)))
                out.append({"id": p.id, "file": p.file, "width": p.width, "height": p.height, "status": p.status,
                            "message": p.message, "lines": len(p.lines), "samples": n,
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
                    "status": p.status, "message": p.message, "line_spacing": p.line_spacing,
                    "image": f"/files/pages/{p.id}?token={token}",
                    "lines": [{"id": ln.id, "number": ln.number, "box": [ln.x, ln.y, ln.w, ln.h], "ink": ln.ink,
                               "image": f"/files/books/{p.book_id}/{ln.image}?token={token}"} for ln in p.lines],
                    "samples": [_sample_json(smp, p.book_id, token) for smp in samples]}

    @app.get("/api/books/{book_id}/groups", dependencies=auth)
    def groups(book_id: int) -> List[Dict]:
        with library.session() as s:
            book = book_or_404(s, book_id)
            ocr = group_suggestions(s, book, library.book_config(book))
            return [_group_json(s, g, token, ocr.get(g.id)) for g in
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
            q = select(Sample).where(Sample.book_id == book_id, Sample.deleted.is_(deleted))
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
            target = Path(book.input_dir) / p.file
        if not target.is_file():
            raise HTTPException(404, f"The input page {p.file} is missing.")
        return FileResponse(target)

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

    return app
