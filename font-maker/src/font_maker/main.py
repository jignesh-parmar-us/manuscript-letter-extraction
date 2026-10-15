"""Start Font Maker (F0): backend on 127.0.0.1, screen in its own window or in the browser.

    python -m font_maker                   own window (pywebview), browser if not available
    python -m font_maker --browser         the default web browser
    python -m font_maker --library DIR     use this library folder (not remembered)
    python -m font_maker --port 8676       the port (default 8676; the reading app uses others)

The library folder is the one the reading app remembers (its settings file), else
`Documents/Manuscript Letters`. Font Maker never changes that setting.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from letter_extractor.app.main import load_settings

from .api import STATIC, create_app
from .store import Store, StoreError

PORT = 8676


def library_dir(arg: Optional[str] = None) -> Path:
    """--library, else the folder the reading app remembers, else the default."""
    if arg:
        return Path(arg).expanduser()
    remembered = load_settings().get("library")
    return Path(remembered) if remembered else Path.home() / "Documents" / "Manuscript Letters"


def _serve(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="backend", daemon=True)
    thread.start()
    for _ in range(200):                                    # wait until it accepts connections
        if server.started or not thread.is_alive():
            break
        time.sleep(0.05)
    return server, thread


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="font-maker", description="Build a font from a book's letter groups.")
    p.add_argument("--browser", action="store_true", help="open in the default web browser, not in a window")
    p.add_argument("--library", help="library folder (default: the one the reading app uses)")
    p.add_argument("--port", type=int, default=PORT, help=f"port (default {PORT})")
    args = p.parse_args(argv)

    if not (STATIC / "index.html").is_file():
        print("The screen is not built yet: run 'npm --prefix font-maker run build'.", file=sys.stderr)
        return 2
    try:
        store = Store(library_dir(args.library))
    except StoreError as e:
        print(e, file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{args.port}/"
    server, thread = _serve(create_app(store, token), args.port)
    if not server.started:
        print(f"Port {args.port} is in use; start with --port <other>.", file=sys.stderr)
        store.close()
        return 2
    print(f"Library: {store.root} (read-only)\nFont Maker: {url}", flush=True)

    shown = False
    if not args.browser:
        try:
            import webview                                  # pywebview
            webview.create_window("Font Maker", url, width=1200, height=850, min_size=(800, 600))
            webview.start()                                 # returns when the window is closed
            shown = True
        except Exception as e:                              # not installed / no window engine
            print(f"No app window available ({e}); opening the browser instead.", file=sys.stderr)
    if not shown:
        webbrowser.open(url)
        print("Press Ctrl+C to stop Font Maker.", flush=True)
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    thread.join(5)
    store.close()
    return 0
