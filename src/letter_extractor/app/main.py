"""Start the review app (C5d): backend on 127.0.0.1 (or --host), screen in its own window or in the browser.

    python -m letter_extractor.app                 own window (pywebview), browser if not available
    python -m letter_extractor.app --browser       the default web browser
    python -m letter_extractor.app --library DIR   use / create this library folder (remembered)
    python -m letter_extractor.app --host 0.0.0.0  also reachable from other devices on the same network

The library folder is remembered in the user's settings file (`settings_path()`); the default is
`Documents/Manuscript Letters`. A random session token is created at every start and written into the
page the app serves at `/`, so the screen can call the API and other web pages cannot (see api.py).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

APP_NAME = "LetterExtractor"
STATIC = Path(__file__).resolve().parent / "static"


def settings_path() -> Path:
    """Per-user settings file of the app (not of a book)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "settings.json"


def load_settings(path: Optional[Path] = None) -> dict:
    path = path or settings_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(values: dict, path: Optional[Path] = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_settings(path)
    data.update(values)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def uploads_dir(library: Path, settings: Optional[Path] = None) -> Path:
    """Where new datasets' and books' uploaded pages go (C20, used from C21): the app setting `uploads`, else
    `<library>/uploads`. Changing it does not move files that are there already (lean plan, decision 5)."""
    chosen = load_settings(settings).get("uploads")
    return Path(chosen).expanduser() if chosen else Path(library) / "uploads"


def unsplit_message(lib) -> Optional[str]:
    """Why the app does not open a library from before Phase 3 (C20), and what to run; None if it is split."""
    rows = lib.unsplit_books()
    if not rows:
        return None
    names = ", ".join(f"'{r['name']}' ({r['read_pages']} Read Book pages)" for r in rows)
    return (f"The library {lib.root} is from before datasets and books were separated: {names} still hold both "
            "parts. Nothing was changed. See what the split does, then run it (it backs the library up first):\n"
            f"  python -m letter_extractor.app.split --library \"{lib.root}\"\n"
            f"  python -m letter_extractor.app.split --library \"{lib.root}\" --run")


def library_dir(arg: Optional[str] = None, settings: Optional[Path] = None) -> Path:
    """--library, else the remembered folder, else the default."""
    from .library import default_library_dir
    if arg:
        return Path(arg).expanduser()
    remembered = load_settings(settings).get("library")
    return Path(remembered) if remembered else default_library_dir()


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def lan_address() -> Optional[str]:
    """This computer's address on the local network, or None (no network)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))                    # no packet is sent; only picks the outgoing interface
            return s.getsockname()[0]
        except OSError:
            return None


def network_url(host: str, port: int, lan: Optional[str] = None) -> Optional[str]:
    """The address other devices open, or None when the app listens on this computer only."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return None
    if host in ("0.0.0.0", "::", ""):
        host = lan or lan_address()
    return f"http://{host}:{port}/" if host else None


def open_path(path: Path) -> None:
    """Show a folder in Finder / Explorer / the file manager."""
    import subprocess
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif os.name == "nt":
        os.startfile(str(path))                                # noqa: S606 (Windows only)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


@dataclass
class AppContext:
    """What the screens need to know about how the app runs (GET /api/app)."""
    mode: str = "browser"                                   # window | browser
    settings_file: Optional[Path] = None
    pick_folder: Optional[Callable[[], Optional[str]]] = None   # folder dialog, window mode only
    static_dir: Path = field(default_factory=lambda: STATIC)
    open_folder: Callable[[Path], None] = open_path            # replaced in tests


def build(library_path: Path, token: str, context: AppContext):
    from .api import create_app
    from .library import Library
    lib = Library(library_path)
    return create_app(lib, token, context=context), lib


def _serve(app, port: int, host: str = "127.0.0.1"):
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="backend", daemon=True)
    thread.start()
    for _ in range(200):                                    # wait until it accepts connections
        if server.started:
            break
        time.sleep(0.05)
    return server, thread


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="letter-extractor-app", description="Manuscript letter review app.")
    p.add_argument("--browser", action="store_true", help="open in the default web browser, not in a window")
    p.add_argument("--library", help="library folder (created if missing; remembered for next time)")
    p.add_argument("--port", type=int, default=0, help="port (default: any free port)")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1: this computer only; 0.0.0.0: also other "
                        "devices on the same network, which can then view and change the library)")
    args = p.parse_args(argv)

    lib_path = library_dir(args.library)
    if args.library:
        save_settings({"library": str(lib_path)})
    if not (STATIC / "index.html").is_file():
        print("The screen is not built yet: run 'npm run build' in frontend/.", file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(24)
    port = args.port or free_port(args.host)
    url = f"http://127.0.0.1:{port}/"

    webview = None
    if not args.browser:
        try:
            import webview  # noqa: F811  (pywebview)
        except Exception as e:                              # not installed / no window engine
            print(f"No app window available ({e}); opening the browser instead.", file=sys.stderr)
            webview = None

    context = AppContext(mode="window" if webview else "browser")
    app, lib = build(lib_path, token, context)
    refused = unsplit_message(lib)
    if refused:
        print(refused, file=sys.stderr)
        lib.close()
        return 3
    server, thread = _serve(app, port, args.host)
    print(f"Library: {lib_path}\nApp: {url}", flush=True)
    other = network_url(args.host, port)
    if other:
        print(f"Other devices on this network: {other}\n"
              "Anyone on this network can open it and change the library.", flush=True)

    if webview is not None:
        window = webview.create_window("Manuscript Letters", url, width=1400, height=900, min_size=(900, 600))

        def pick() -> Optional[str]:
            chosen = window.create_file_dialog(webview.FOLDER_DIALOG)
            return chosen[0] if chosen else None

        context.pick_folder = pick
        try:
            webview.start()                                 # returns when the window is closed
        except Exception as e:
            print(f"The app window could not start ({e}); opening the browser instead.", file=sys.stderr)
            context.mode, context.pick_folder = "browser", None
            webview = None
    if webview is None:
        webbrowser.open(url)
        print("Press Ctrl+C to stop the app.", flush=True)
        try:
            while thread.is_alive():
                thread.join(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    thread.join(5)
    lib.close()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
