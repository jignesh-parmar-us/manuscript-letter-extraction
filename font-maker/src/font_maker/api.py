"""Font Maker's backend (F0-F11). `create_app(store, token)` returns the app.

As in the reading app, every request must carry the session token created at start: in the `X-Token`
header, or as `?token=` (for files a tag loads). `GET /` serves the built screen with the token in it.

  app      GET /api/app        name, version, library folder, number of books
  sources  GET /api/sources    the books, with their groups counted per status (F1)
  fonts    GET/POST /api/fonts, GET/PATCH/DELETE /api/fonts/{id}   the font projects (F1, projects.py)
  glyphs   POST /api/fonts/{id}/glyphs/check   bring the glyphs up to date (in the background when needed)
           GET  /api/fonts/{id}/glyphs         the glyphs, kept in memory, and the progress (F2, glyphs.py)
           GET  /api/fonts/{id}/glyphs/{group}/copies   a group's copies to pick from
           PUT  /api/fonts/{id}/glyphs/{group}/choice   system pick / one copy / left out / keep
           GET  /api/fonts/{id}/glyphs/{group}/outline  the traced outline as an SVG path (F4, trace.py)
           PUT  /api/fonts/{id}/glyphs/{group}/headline even this glyph's headline or not (F8, headline.py)
  build    GET  /api/fonts/{id}/build    the newest build's report, the coverage now, the build job (F5)
           POST /api/fonts/{id}/build    build the next version (in the background)
           PUT  /api/fonts/{id}/filled   fill missing characters from the normal font, or take the fill out
           PUT  /api/fonts/{id}/generated   generate signs from the book's aksharas, or take them out (F9, gen.py)
           PUT/DELETE /api/fonts/{id}/drawn/{char}   a letter you drew or uploaded (F11), or take it out
  try it   POST /api/fonts/{id}/coverage   how the newest build draws a text, akshara by akshara (F6, tryit.py)
           GET/PUT /api/fonts/{id}/texts, DELETE /api/fonts/{id}/texts/{text}   test texts (F7, texts.py)
           GET  /api/fonts/{id}/coverage/texts   the test texts with the newest build and the one before
           POST /api/fonts/{id}/export/{png|pdf|docx}   the text in the newest build (F7, export.py)
  help     GET /help/font.html             the help page (no token; copied from font-maker/docs/help/ by the build)
  files    GET /files/fonts/{id}/glyphs/{name} (a glyph image), GET /files/fonts/{id}/builds/{name} (a .ttf),
           GET /files/books/{id}/{path} (a copy's image)
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
from . import export
from .texts import Texts
from .tryit import classify
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"


class NewFont(BaseModel):
    name: str
    book_id: int
    statuses: Optional[List[str]] = None


class FontChange(BaseModel):
    name: Optional[str] = None
    statuses: Optional[List[str]] = None
    mark_filled: Optional[bool] = None
    clean_headline: Optional[bool] = None


class HeadlineChoice(BaseModel):
    on: bool


class TryText(BaseModel):
    text: str


class TestText(BaseModel):
    name: str
    text: str
    id: Optional[str] = None


class ExportText(BaseModel):
    text: str
    size: Optional[float] = None      # png: pixels an em; pdf, docx: points


class Fill(BaseModel):
    chars: List[str]
    filled: bool = True


class Drawn(BaseModel):
    png: str                          # base64 (a data: URL is fine)
    baseline: Optional[float] = None  # drawn on the pad: its baseline row and pad pixels per page pixel
    px_per_page_px: Optional[float] = None


class Generate(BaseModel):
    chars: List[str]
    on: bool = True


class Choice(BaseModel):
    choice: str                       # system | copy | left_out | keep
    sample: Optional[int] = None


def create_app(store: Store, token: str, static_dir: Optional[Path] = None) -> FastAPI:
    static_dir = static_dir or STATIC
    app = FastAPI(title="Font Maker", version=__version__)
    projects = Projects(store.fonts_dir)
    maker = GlyphMaker(store, projects)
    texts = Texts(store, projects)
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
        return projects.update(font_id, name=body.name, statuses=body.statuses, mark_filled=body.mark_filled,
                               clean_headline=body.clean_headline)

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

    @app.get("/api/fonts/{font_id}/glyphs/{group_id}/outline", dependencies=auth)
    def outline(font_id: str, group_id: int) -> Dict:
        return maker.svg(font_id, group_id)

    @app.put("/api/fonts/{font_id}/glyphs/{group_id}/headline", dependencies=auth)
    def headline_choice(font_id: str, group_id: int, body: HeadlineChoice) -> Dict:
        return maker.set_headline(font_id, group_id, body.on)

    @app.put("/api/fonts/{font_id}/glyphs/{group_id}/choice", dependencies=auth)
    def choose(font_id: str, group_id: int, body: Choice) -> Dict:
        return maker.choose(font_id, group_id, body.choice, body.sample)

    # ---- the font (F5) ---------------------------------------------------------------------------------
    @app.get("/api/fonts/{font_id}/build", dependencies=auth)
    def build_state(font_id: str) -> Dict:
        return maker.build_state(font_id)

    @app.post("/api/fonts/{font_id}/build", dependencies=auth)
    def build(font_id: str) -> Dict:
        return maker.start_build(font_id)

    @app.put("/api/fonts/{font_id}/filled", dependencies=auth)
    def fill(font_id: str, body: Fill) -> Dict:
        projects.set_filled(font_id, body.chars, body.filled)
        return maker.build_state(font_id)

    @app.post("/api/fonts/{font_id}/coverage", dependencies=auth)
    def try_coverage(font_id: str, body: TryText) -> Dict:
        report = maker.build_state(font_id)["report"]
        if not report:
            raise ProjectError("Build the font first (Build tab).")
        return classify(body.text[:5000], report)

    @app.put("/api/fonts/{font_id}/generated", dependencies=auth)
    def generate(font_id: str, body: Generate) -> Dict:
        return maker.set_generated(font_id, body.chars, body.on)

    @app.put("/api/fonts/{font_id}/drawn/{char}", dependencies=auth)
    def drawn(font_id: str, char: str, body: Drawn) -> Dict:
        import base64
        data = body.png.split(",", 1)[1] if body.png.startswith("data:") else body.png
        try:
            png = base64.b64decode(data, validate=True)
        except ValueError:
            raise ProjectError("The picture could not be read.")
        if len(png) > 8_000_000:
            raise ProjectError("The picture is larger than 8 MB.")
        return maker.set_drawn(font_id, char, png, body.baseline, body.px_per_page_px)

    @app.delete("/api/fonts/{font_id}/drawn/{char}", dependencies=auth)
    def remove_drawn(font_id: str, char: str) -> Dict:
        return maker.remove_drawn(font_id, char)

    @app.get("/files/fonts/{font_id}/drawn/{name}", dependencies=auth)
    def drawn_file(font_id: str, name: str):
        return FileResponse(_png_in(projects.dir / font_id / "glyphs" / "drawn", name),
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    # ---- test texts and downloads (F7) ---------------------------------------------------------------
    @app.get("/api/fonts/{font_id}/texts", dependencies=auth)
    def list_texts(font_id: str) -> List[Dict]:
        return texts.list(font_id)

    @app.put("/api/fonts/{font_id}/texts", dependencies=auth)
    def save_text(font_id: str, body: TestText) -> Dict:
        return texts.save(font_id, body.name, body.text, body.id)

    @app.delete("/api/fonts/{font_id}/texts/{text_id}", dependencies=auth, status_code=204)
    def delete_text(font_id: str, text_id: str) -> Response:
        texts.delete(font_id, text_id)
        return Response(status_code=204)

    @app.get("/api/fonts/{font_id}/coverage/texts", dependencies=auth)
    def texts_coverage(font_id: str) -> List[Dict]:
        return texts.coverage(font_id, maker.reports(font_id))

    @app.post("/api/fonts/{font_id}/export/{fmt}", dependencies=auth)
    def export_text(font_id: str, fmt: str, body: ExportText) -> Response:
        if fmt not in ("png", "pdf", "docx"):
            raise HTTPException(404, "Download as png, pdf or docx.")
        path, report = maker.newest_font(font_id)
        text = body.text[:20000]
        if fmt == "png":
            data, media = export.png(path, text, int(body.size or 64)), "image/png"
        elif fmt == "pdf":
            data, media = export.pdf(path, text, body.size or 18.0), "application/pdf"
        else:
            data = export.docx(path, report["family"], text, body.size or 18.0)
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        name = path.name.rsplit("-", 1)[0] + "." + fmt
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ---- files (read-only) -----------------------------------------------------------------------------
    def _png_in(root: Path, path: str) -> Path:
        root = root.resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() != ".png":
            raise HTTPException(404, "No such file.")
        return target

    @app.get("/files/fonts/{font_id}/generated/{name}", dependencies=auth)
    def generated_file(font_id: str, name: str):
        return FileResponse(_png_in(projects.dir / font_id / "glyphs" / "generated", name),
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/files/fonts/{font_id}/glyphs/{name}", dependencies=auth)
    def glyph_file(font_id: str, name: str):
        # the name holds the glyph's fingerprint: a changed glyph has a new name, so it may be cached
        return FileResponse(_png_in(projects.dir / font_id / "glyphs", name),
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/files/fonts/{font_id}/builds/{name}", dependencies=auth)
    def font_file(font_id: str, name: str):
        root = (projects.dir / font_id / "builds").resolve()
        target = (root / name).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() != ".ttf":
            raise HTTPException(404, "No such font file.")
        return FileResponse(target, media_type="font/ttf", filename=target.name,
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
    if (static_dir / "help").is_dir():
        # the help page (copied from font-maker/docs/help/ by the screen's build); no data, so no token needed
        app.mount("/help", StaticFiles(directory=static_dir / "help", html=True), name="help")

    return app
