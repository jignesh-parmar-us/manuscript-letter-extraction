"""Font Maker's backend (F0, F1). `create_app(store, token)` returns the app.

As in the reading app, every request must carry the session token created at start: in the `X-Token`
header, or as `?token=` (for files a tag loads). `GET /` serves the built screen with the token in it.

  app      GET /api/app        name, version, library folder, number of books
  sources  GET /api/sources    the books, with their groups counted per status (F1)
  fonts    GET/POST /api/fonts, GET/PATCH/DELETE /api/fonts/{id}   the font projects (F1, projects.py)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
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


def create_app(store: Store, token: str, static_dir: Optional[Path] = None) -> FastAPI:
    static_dir = static_dir or STATIC
    app = FastAPI(title="Font Maker", version=__version__)
    projects = Projects(store.fonts_dir)
    app.state.store, app.state.token, app.state.projects = store, token, projects

    def check_token(x_token: Optional[str] = Header(default=None),
                    q_token: Optional[str] = Query(default=None, alias="token")):
        if token and (x_token or q_token) != token:
            raise HTTPException(status_code=401, detail="Missing or wrong session token.")

    auth = [Depends(check_token)]

    @app.exception_handler(ProjectError)
    async def _project_error(request: Request, e: ProjectError):
        return JSONResponse({"detail": str(e)}, status_code=404 if isinstance(e, ProjectNotFound) else 400)

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
        return Response(status_code=204)

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
