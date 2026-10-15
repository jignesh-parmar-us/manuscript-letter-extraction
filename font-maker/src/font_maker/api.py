"""Font Maker's backend (F0-F2). `create_app(store, token)` returns the app.

As in the reading app, every request must carry the session token created at start: in the `X-Token`
header, or as `?token=` (for files a tag loads). `GET /` serves the built screen with the token in it.

  app      GET /api/app        name, version, library folder, number of books
  sources  GET /api/sources    the books, with their groups counted per status (F1)
  fonts    GET/POST /api/fonts, GET/PATCH/DELETE /api/fonts/{id}   the font projects (F1, projects.py)
  glyphs   POST /api/fonts/{id}/glyphs/check   bring the glyphs up to date (in the background when needed)
           GET  /api/fonts/{id}/glyphs         the glyphs, kept in memory, and the progress (F2, glyphs.py)
           GET  /api/fonts/{id}/glyphs/{group}/copies   a group's copies to pick from
           PUT  /api/fonts/{id}/glyphs/{group}/choice   system pick / one copy / left out / keep
  files    GET /files/fonts/{id}/glyphs/{name} (a glyph image), GET /files/books/{id}/{path} (a copy's image)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from letter_extractor.app.db import Book

from .glyphs import Busy, GlyphMaker
from .projects import ProjectError, ProjectNotFound, Projects
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"


class NewFont(BaseModel):
    name: str
    book_id: int
    statuses: Optional[List[str]] = None


class FontChange(BaseModel):
    name: Optional[str] = None
    statuses: Optional[List[str]] = None


class Choice(BaseModel):
    choice: str                       # system | copy | left_out | keep
    sample: Optional[int] = None


def create_app(store: Store, token: str, static_dir: Optional[Path] = None) -> FastAPI:
    static_dir = static_dir or STATIC
    app = FastAPI(title="Font Maker", version=__version__)
    projects = Projects(store.fonts_dir)
    maker = GlyphMaker(store, projects)
    app.state.store, app.state.token, app.state.projects, app.state.maker = store, token, projects, maker

    def check_token(x_token: Optional[str] = Header(default=None),
                    q_token: Optional[str] = Query(default=None, alias="token")):
        if token and (x_token or q_token) != token:
            raise HTTPException(status_code=401, detail="Missing or wrong session token.")

    auth = [Depends(check_token)]

    @app.exception_handler(ProjectError)
    async def _project_error(request: Request, e: ProjectError):
        code = 404 if isinstance(e, ProjectNotFound) else 409 if isinstance(e, Busy) else 400
        return JSONResponse({"detail": str(e)}, status_code=code)

    @app.get("/api/app", dependencies=auth)
    def app_info() -> Dict:
        return {"name": "Font Maker", "version": __version__, "library": str(store.root),
                "books": store.book_count()}

    @app.get("/api/sources", dependencies=auth)
    def sources() -> List[Dict]:
        return store.sources()

    # ---- font projects ---------------------------------------------------------------------------------
    @app.get("/api/fonts", dependencies=auth)
    def list_fonts() -> List[Dict]:
        return projects.list()

    @app.post("/api/fonts", dependencies=auth, status_code=201)
    def create_font(body: NewFont) -> Dict:
        if body.book_id not in {b["id"] for b in store.sources()}:
            raise ProjectError(f"No book {body.book_id} in the library.")
        return projects.create(body.name, [body.book_id], body.statuses)

    @app.get("/api/fonts/{font_id}", dependencies=auth)
    def get_font(font_id: str) -> Dict:
        return projects.get(font_id)

    @app.patch("/api/fonts/{font_id}", dependencies=auth)
    def change_font(font_id: str, body: FontChange) -> Dict:
        return projects.update(font_id, name=body.name, statuses=body.statuses)

    @app.delete("/api/fonts/{font_id}", dependencies=auth, status_code=204)
    def delete_font(font_id: str) -> Response:
        projects.delete(font_id)
        maker.forget(font_id)
        return Response(status_code=204)

    # ---- glyphs (F2) -----------------------------------------------------------------------------------
    @app.post("/api/fonts/{font_id}/glyphs/check", dependencies=auth)
    def check_glyphs(font_id: str) -> Dict:
        return maker.start(font_id)

    @app.get("/api/fonts/{font_id}/glyphs", dependencies=auth)
    def glyphs(font_id: str) -> Dict:
        return maker.state(font_id)

    @app.get("/api/fonts/{font_id}/glyphs/{group_id}/copies", dependencies=auth)
    def copies(font_id: str, group_id: int) -> List[Dict]:
        return maker.copies(font_id, group_id)

    @app.put("/api/fonts/{font_id}/glyphs/{group_id}/choice", dependencies=auth)
    def choose(font_id: str, group_id: int, body: Choice) -> Dict:
        return maker.choose(font_id, group_id, body.choice, body.sample)

    # ---- files (read-only) -----------------------------------------------------------------------------
    def _png_in(root: Path, path: str) -> Path:
        root = root.resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() != ".png":
            raise HTTPException(404, "No such file.")
        return target

    @app.get("/files/fonts/{font_id}/glyphs/{name}", dependencies=auth)
    def glyph_file(font_id: str, name: str):
        # the name holds the glyph's fingerprint: a changed glyph has a new name, so it may be cached
        return FileResponse(_png_in(projects.dir / font_id / "glyphs", name),
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/files/books/{book_id}/{path:path}", dependencies=auth)
    def book_file(book_id: int, path: str):
        with store.session() as s:
            book = s.get(Book, book_id)
            if book is None:
                raise HTTPException(404, f"No book {book_id}.")
            folder = book.folder
        return FileResponse(_png_in(store.root / "books" / folder, path), headers={"Cache-Control": "no-cache"})

    # ---- the screen ------------------------------------------------------------------------------------
    index = static_dir / "index.html"

    @app.get("/", include_in_schema=False)
    def screen():
        if not index.is_file():
            return HTMLResponse("<h1>The screen is not built</h1><p>Run <code>npm --prefix font-maker run build"
                                "</code>.</p>", status_code=503)
        html = index.read_text(encoding="utf-8")
        tag = f"<script>window.__TOKEN__ = {json.dumps(token)};</script>"
        return HTMLResponse(html.replace("</head>", tag + "</head>", 1), headers={"Cache-Control": "no-store"})

    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    return app
