"""Tesseract as the reader of printed lines (C10).

Tesseract is a separate install (docs/INSTALL_TESSERACT.md). It is called as a program, never through
a Python wrapper: the line image goes in as a temporary PNG, and hOCR with one box, confidence and
list of alternatives per character comes out. The boxes are returned in the coordinates of the
image that was passed in, whatever scaling and border the preparation added.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

INSTALL_HELP = "See docs/INSTALL_TESSERACT.md."

# where installers put the program when it is not on the PATH (a desktop app often gets a short PATH)
_USUAL_PLACES = ["/opt/local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
                 r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"]

Box = Tuple[int, int, int, int]          # x, y, w, h


class TesseractError(Exception):
    """Tesseract is missing, lacks a language, or failed on an image (the message says which)."""


@dataclass
class Engine:
    path: str
    version: str
    langs: List[str]

    def check_langs(self, langs: str) -> None:
        missing = [lang for lang in langs.split("+") if lang not in self.langs]
        if missing:
            raise TesseractError(f"Tesseract has no language model {', '.join(missing)} "
                                 f"(installed: {', '.join(self.langs) or 'none'}). {INSTALL_HELP}")


@dataclass
class Char:
    text: str
    box: Box
    conf: float                                                  # 0 to 100
    alternatives: List[Tuple[str, float]] = field(default_factory=list)   # (text, confidence), best first


@dataclass
class Word:
    box: Box
    conf: float
    chars: List[Char]

    @property
    def text(self) -> str:
        return "".join(c.text for c in self.chars)


@dataclass
class LineReading:
    words: List[Word]
    hocr: str                                # raw output, kept so a line can be aligned again
    scale: float                             # image size given to Tesseract / input image size

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def chars(self) -> List[Char]:
        return [c for w in self.words for c in w.chars]


def _run(args: Sequence[str], timeout: float, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    # no console window per call on Windows
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    full_env = {**os.environ, **env} if env else None
    return subprocess.run(list(args), capture_output=True, timeout=timeout, creationflags=flags, env=full_env)


def find_tesseract(setting: str = "") -> Engine:
    """The program from the app setting, else from the PATH, else from the usual install folders,
    with its version and installed languages."""
    candidates: List[str] = []
    if setting:
        candidates.append(setting)
    on_path = shutil.which("tesseract")
    if on_path:
        candidates.append(on_path)
    exe = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    candidates += [os.path.join(d, exe) for d in _USUAL_PLACES]
    path = next((c for c in candidates if os.path.isfile(c) and os.access(c, os.X_OK)), None)
    if path is None:
        where = f" (not at the set path {setting})" if setting else ""
        raise TesseractError(f"Tesseract is not installed{where}. {INSTALL_HELP}")
    try:
        ver = _run([path, "--version"], 30)
        lst = _run([path, "--list-langs"], 30)
    except (OSError, subprocess.SubprocessError) as e:
        raise TesseractError(f"Cannot run Tesseract at {path}: {e}. {INSTALL_HELP}") from e
    out = (ver.stdout or ver.stderr).decode("utf-8", "replace")
    m = re.search(r"tesseract\s+v?(\S+)", out)
    langs = [s.strip() for s in lst.stdout.decode("utf-8", "replace").splitlines()[1:] if s.strip()]
    return Engine(path=path, version=m.group(1) if m else "?", langs=sorted(langs))


# ---- image preparation ------------------------------------------------------------------------

def letter_height(ink: np.ndarray) -> float:
    """Height of the letter bodies (headline to foot) of a line's ink mask: the rows where most
    columns with ink have ink (at least 35% of the busiest row, the headline). Upper and lower
    vowel signs cover few columns, so they fall out."""
    cols = ink.any(axis=0)
    if not cols.any():
        return 0.0
    rows = ink[:, cols].mean(axis=1)
    body = np.flatnonzero(rows >= 0.35 * rows.max())
    return float(body[-1] - body[0] + 1) if body.size else 0.0


def ink_mask(rgb: np.ndarray) -> np.ndarray:
    """Ink of a line image (dark or coloured on paper) by Otsu's threshold on the lightness."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask > 0


def prepare_line(rgb: np.ndarray, target_height: int = 40, border: int = 10,
                 ink: Optional[np.ndarray] = None) -> Tuple[np.ndarray, float]:
    """Black ink on white, a white border, scaled so the letter bodies are `target_height` px tall
    (0: no scaling). Returns the image and the scale used."""
    if ink is None:
        ink = ink_mask(rgb)
    img = np.where(ink, 0, 255).astype(np.uint8)
    scale = 1.0
    if target_height > 0:
        h = letter_height(ink)
        if h > 0:
            scale = target_height / h
    if abs(scale - 1.0) > 0.02:
        size = (max(1, round(img.shape[1] * scale)), max(1, round(img.shape[0] * scale)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    else:
        scale = 1.0
    img = cv2.copyMakeBorder(img, border, border, border, border, cv2.BORDER_CONSTANT, value=255)
    return img, scale


# ---- hOCR ---------------------------------------------------------------------------------------

def _title_value(title: str, key: str) -> List[float]:
    for part in title.split(";"):
        bits = part.split()
        if bits and bits[0] == key:
            return [float(v) for v in bits[1:]]
    return []


class _HocrParser(HTMLParser):
    """Words (`ocrx_word`) → characters (`ocrx_cinfo` with `x_bboxes`), each followed by its
    `lstm_choices` block of alternatives (`choice_*` with `x_confs`)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.words: List[Word] = []
        self._stack: List[str] = []          # role of every open span / div / p
        self._char: Optional[Char] = None    # character whose text is being read
        self._choice: Optional[List] = None  # [text, conf] of the alternative being read
        self._last: Optional[Char] = None    # character the next lstm_choices block belongs to

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls, ident, title = a.get("class", ""), a.get("id") or "", a.get("title") or ""
        role = ""
        if cls == "ocrx_word":
            box = _title_value(title, "bbox")
            conf = _title_value(title, "x_wconf")
            self.words.append(Word(box=_box(box), conf=conf[0] if conf else 0.0, chars=[]))
            role = "word"
        elif cls == "ocrx_cinfo" and ident.startswith("choice_"):
            conf = _title_value(title, "x_confs")
            self._choice = ["", conf[0] if conf else 0.0]
            role = "choice"
        elif cls == "ocrx_cinfo" and ident.startswith("lstm_choices"):
            role = "choices"
        elif cls == "ocrx_cinfo" and "x_bboxes" in title and self.words:
            conf = _title_value(title, "x_conf")
            self._char = Char(text="", box=_box(_title_value(title, "x_bboxes")), conf=conf[0] if conf else 0.0)
            role = "char"
        if tag not in ("meta", "br", "img"):
            self._stack.append(role)

    def handle_endtag(self, tag):
        if not self._stack:
            return
        role = self._stack.pop()
        if role == "char" and self._char is not None:
            if self._char.text:
                self.words[-1].chars.append(self._char)
                self._last = self._char
            self._char = None
        elif role == "choice" and self._choice is not None:
            if self._last is not None and self._choice[0]:
                self._last.alternatives.append((self._choice[0], self._choice[1]))
            self._choice = None

    def handle_data(self, data):
        if self._choice is not None:
            self._choice[0] += data.strip()
        elif self._char is not None:
            self._char.text += data.strip()


def _box(v: List[float]) -> Box:
    if len(v) < 4:
        return (0, 0, 0, 0)
    x0, y0, x1, y1 = (int(round(t)) for t in v[:4])
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))


def parse_hocr(hocr: str) -> List[Word]:
    """Words with their characters; alternatives are sorted best first. Empty words are dropped."""
    p = _HocrParser()
    p.feed(hocr)
    p.close()
    for w in p.words:
        for c in w.chars:
            c.alternatives.sort(key=lambda t: -t[1])
    return [w for w in p.words if w.chars]


def _unscale(box: Box, scale: float, border: int) -> Box:
    x, y, w, h = box
    if w == 0 and h == 0:
        return box
    return (int(round((x - border) / scale)), int(round((y - border) / scale)),
            int(round(w / scale)), int(round(h / scale)))


def map_boxes(words: List[Word], scale: float, border: int) -> List[Word]:
    """Boxes from Tesseract's image back to the input image's coordinates."""
    for w in words:
        w.box = _unscale(w.box, scale, border)
        for c in w.chars:
            c.box = _unscale(c.box, scale, border)
    return words


# ---- reading a line ---------------------------------------------------------------------------

def run_hocr(engine: Engine, image: np.ndarray, langs: str, psm: int, timeout: float = 60,
             env: Optional[Dict[str, str]] = None) -> str:
    """hOCR of one prepared image. The PNG goes through Pillow (Unicode-safe temporary path).
    `env` adds environment variables, for example OMP_THREAD_LIMIT=1 when several run at once."""
    engine.check_langs(langs)
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ocr-")
    os.close(fd)
    try:
        Image.fromarray(image).save(tmp, format="PNG", dpi=(300, 300))
        args = [engine.path, tmp, "-", "-l", langs, "--psm", str(psm),
                "-c", "hocr_char_boxes=1", "-c", "lstm_choice_mode=2", "hocr"]
        try:
            r = _run(args, timeout, env)
        except subprocess.TimeoutExpired as e:
            raise TesseractError(f"Tesseract took longer than {timeout:.0f} s on one line.") from e
        except OSError as e:
            raise TesseractError(f"Cannot run Tesseract at {engine.path}: {e}. {INSTALL_HELP}") from e
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise TesseractError(f"Tesseract failed: {err[-1] if err else f'exit code {r.returncode}'}")
    return r.stdout.decode("utf-8", "replace")


def read_line(rgb: np.ndarray, engine: Engine, langs: str = "script/Devanagari", psm: int = 7,
              target_height: int = 0, border: int = 10, ink: Optional[np.ndarray] = None,
              timeout: float = 60, env: Optional[Dict[str, str]] = None) -> LineReading:
    """Read one line image. Boxes in the result are in `rgb`'s coordinates."""
    img, scale = prepare_line(rgb, target_height, border, ink)
    hocr = run_hocr(engine, img, langs, psm, timeout, env)
    return LineReading(words=map_boxes(parse_hocr(hocr), scale, border), hocr=hocr, scale=scale)


def reading_from_hocr(hocr: str, scale: float = 1.0, border: int = 10) -> LineReading:
    """A saved hOCR read back (no Tesseract needed)."""
    return LineReading(words=map_boxes(parse_hocr(hocr), scale, border), hocr=hocr, scale=scale)


def load_rgb(path: Path) -> np.ndarray:
    from ..io_utils import load_image
    return load_image(path)[0]
