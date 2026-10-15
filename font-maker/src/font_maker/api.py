"""Font Maker's backend (F0). `create_app(store, token)` returns the app.

As in the reading app, every request must carry the session token created at start: in the `X-Token`
header, or as `?token=` (for files a tag loads). `GET /` serves the built screen with the token in it.

  app     GET /api/app   name, version, library folder, number of books
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"


def create_app(store: Store, token: str, static_dir: Optional[Path] = None) -> FastAPI:
    static_dir = static_dir or STATIC
    app = FastAPI(title="Font Maker", version=__version__)
    app.state.store, app.state.token = store, token

    def check_token(x_token: Optional[str] = Header(default=None),
                    q_token: Optional[str] = Query(default=None, alias="token")):
        if token and (x_token or q_token) != token:
            raise HTTPException(status_code=401, detail="Missing or wrong session token.")

    auth = [Depends(check_token)]

    @app.get("/api/app", dependencies=auth)
    def app_info() -> Dict:
        return {"name": "Font Maker", "version": __version__, "library": str(store.root),
                "books": store.book_count()}

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
