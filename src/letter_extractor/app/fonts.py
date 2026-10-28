"""Fonts to show and download a book's text in (custom fonts, T1; docs/plans/done/CUSTOM_FONT_PLAN.md).

The fonts are the library's, not a book's: `<library>/display_fonts/<id>.json` describes each, next to the font
file for an upload (`<id>.ttf` or `<id>.otf`). An upload's id is the first 12 hex digits of its SHA-256, so the
same file uploaded twice is one font. A font built in Font Maker is a reference (`"source": "fontmaker"`) to
its project in `<library>/fonts/<project>/`: it always uses the project's latest build, read only (Font Maker
owns that folder, and this package never imports font_maker).

Only Unicode fonts are taken: an old-style font (Shree-Lipi, Terafont, Kruti Dev, ...) draws its letters on
English key codes, so Unicode text would show as nonsense in it; it is refused with a message saying so.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SUFFIXES = (".ttf", ".otf", ".ttc")
MAX_FONT = 30 * 1024 * 1024
# the characters a font is checked for: the Devanagari and Gujarati blocks
BLOCKS = {"devanagari": (0x0900, 0x097F), "gujarati": (0x0A80, 0x0AFF)}
CONSONANTS = {"devanagari": (0x0915, 0x0939), "gujarati": (0x0A95, 0x0AB9)}
MIN_CONSONANTS = 10
MIN_SIZE, MAX_SIZE = 0.5, 2.0   # your size for a font (A- / A+), times the matched size        # a script counts when the font has at least this many of its consonants
_ID = re.compile(r"^[0-9a-f]{12}$|^fm-f\d{4}$")
_PROJECT = re.compile(r"^f\d{4}$")

OLD_STYLE = ("This font has no Gujarati or Devanagari letters. If it is an old-style (non-Unicode) font, such as "
             "Shree-Lipi, Terafont or Kruti Dev, it draws its letters on English key codes, so the text would show "
             "as nonsense in it: converting text for such fonts is not built yet. Choose a Unicode Gujarati or "
             "Devanagari font.")


class FontError(ValueError):
    """Not a font that can be used (with the reason, for the screen)."""


class FontNotFound(KeyError):
    pass


@dataclass
class FontInfo:
    family: str
    scripts: List[str]          # "gujarati", "devanagari"
    chars: str                  # the font's characters of the two blocks
    embeddable: bool            # may be embedded in a Word file (not restricted, TrueType outlines)
    joins: bool = True          # has OpenType rules (GSUB) to join conjuncts and vowel signs; some Apple fonts
                                # have only Apple's own (morx), which Word on Windows does not use


def inspect(data: bytes) -> FontInfo:
    """What a font file is: its family name, scripts and characters. FontError for a file that is not a font,
    a font collection or an old-style font."""
    from fontTools.ttLib import TTFont, TTLibError
    if data[:4] == b"ttcf":
        raise FontError("A font collection (.ttc): take one font out of it first (from_collection).")
    try:
        font = TTFont(io.BytesIO(data), lazy=True)
        cmap = font.getBestCmap() or {}
        names = font["name"]
        family = str(names.getBestFamilyName() or "").strip()
        fs_type = font["OS/2"].fsType if "OS/2" in font else 0
        truetype = "glyf" in font
        joins = "GSUB" in font
    except (TTLibError, KeyError, AssertionError, ValueError, struct.error) as e:
        raise FontError(f"This is not a font file that can be read ({e}).") from e
    scripts = [s for s, (a, b) in CONSONANTS.items()
               if sum(c in cmap for c in range(a, b + 1)) >= MIN_CONSONANTS]
    if not scripts:
        raise FontError(OLD_STYLE)
    chars = "".join(chr(c) for a, b in BLOCKS.values() for c in range(a, b + 1) if c in cmap)
    restricted = (fs_type & 0x000F) == 0x0002
    # Gujarati first: the reading app's own script order
    scripts.sort(key=lambda s: s != "gujarati")
    return FontInfo(family or "Font", scripts, chars, truetype and not restricted, joins)


def from_collection(data: bytes) -> bytes:
    """The Regular font of a font collection (.ttc; the Gujarati and Devanagari fonts of macOS are collections),
    or its first, as a font file of its own: browsers and Word take single fonts only."""
    from fontTools.ttLib import TTLibError
    from fontTools.ttLib.ttCollection import TTCollection
    try:
        fonts = TTCollection(io.BytesIO(data)).fonts
    except (TTLibError, KeyError, AssertionError, ValueError, struct.error) as e:
        raise FontError(f"This font collection cannot be read ({e}).") from e
    if not fonts:
        raise FontError("This font collection is empty.")

    def style(f) -> str:
        return str(f["name"].getDebugName(2) or "").lower()
    font = next((f for f in fonts if style(f) == "regular"), fonts[0])
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


@lru_cache(maxsize=64)
def _inspect_file(path: str, mtime: float) -> FontInfo:
    return inspect(Path(path).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Fonts:
    """The library's fonts for the text screens."""

    def __init__(self, library_root: Path):
        self.root = Path(library_root)
        self.dir = self.root / "display_fonts"
        self.fontmaker_dir = self.root / "fonts"

    # ---- reading -----------------------------------------------------------------------------------------
    def _meta(self, font_id: str) -> Dict:
        if not _ID.match(font_id or ""):
            raise FontNotFound(font_id)
        path = self.dir / f"{font_id}.json"
        if not path.is_file():
            raise FontNotFound(font_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _latest_build(self, project: str) -> Optional[Path]:
        builds = self.fontmaker_dir / project / "builds"
        files = sorted(builds.glob("*.ttf"), key=lambda p: p.stat().st_mtime) if builds.is_dir() else []
        return files[-1] if files else None

    def path(self, font_id: str) -> Path:
        """The font file of a font (for a Font Maker font: its project's latest build)."""
        meta = self._meta(font_id)
        if meta.get("source") == "fontmaker":
            got = self._latest_build(meta["project"])
            if got is None:
                raise FontNotFound(font_id)
            return got
        got = self.dir / meta["file"]
        if not got.is_file():
            raise FontNotFound(font_id)
        return got

    def info(self, font_id: str) -> FontInfo:
        p = self.path(font_id)
        return _inspect_file(str(p), p.stat().st_mtime)

    def _entry(self, meta: Dict) -> Optional[Dict]:
        try:
            p = self.path(meta["id"])
            info = _inspect_file(str(p), p.stat().st_mtime)
        except (FontNotFound, FontError, OSError):
            return None
        return {"id": meta["id"], "name": meta["name"], "source": meta.get("source", "upload"),
                "family": info.family, "scripts": info.scripts, "chars": info.chars,
                "embeddable": info.embeddable, "joins": info.joins, "size": meta.get("size", 1.0),
                "added_at": meta.get("added_at"),
                "version": int(p.stat().st_mtime)}

    def list(self) -> List[Dict]:
        """The added fonts, oldest first (a Font Maker font with no build is left out)."""
        metas = self._all_metas()
        metas.sort(key=lambda m: (m.get("added_at") or "", m.get("id", "")))
        return [e for e in (self._entry(m) for m in metas) if e is not None]

    def get(self, font_id: str) -> Dict:
        got = self._entry(self._meta(font_id))
        if got is None:
            raise FontNotFound(font_id)
        return got

    # ---- adding and removing -----------------------------------------------------------------------------
    def _write_meta(self, meta: Dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{meta['id']}.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / f"{meta['id']}.json")

    def add_upload(self, filename: str, data: bytes) -> Dict:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in SUFFIXES:
            raise FontError("Choose a .ttf, .otf or .ttc font file.")
        if not data:
            raise FontError(f"'{filename}' is empty.")
        if len(data) > MAX_FONT:
            raise FontError(f"'{filename}' is too large for a font ({len(data) // (1024 * 1024)} MB).")
        if data[:4] == b"ttcf":
            data = from_collection(data)
            suffix = ".otf" if data[:4] == b"OTTO" else ".ttf"
        info = inspect(data)
        font_id = hashlib.sha256(data).hexdigest()[:12]
        if (self.dir / f"{font_id}.json").is_file():
            return self.get(font_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        part = self.dir / f".{font_id}{suffix}.part"
        part.write_bytes(data)
        os.replace(part, self.dir / f"{font_id}{suffix}")
        name = info.family if info.family != "Font" else Path(filename).stem
        self._write_meta({"id": font_id, "name": name, "source": "upload", "file": f"{font_id}{suffix}",
                          "original": Path(filename).name, "added_at": _now()})
        return self.get(font_id)

    def fontmaker_fonts(self) -> List[Dict]:
        """Font Maker's fonts with at least one build, to pick from (read only)."""
        if not self.fontmaker_dir.is_dir():
            return []
        added = {m["project"] for m in self._all_metas() if m.get("source") == "fontmaker"}
        out = []
        for folder in sorted(self.fontmaker_dir.iterdir()):
            if not _PROJECT.match(folder.name) or not (folder / "font.json").is_file():
                continue
            build = self._latest_build(folder.name)
            if build is None:
                continue
            try:
                name = json.loads((folder / "font.json").read_text(encoding="utf-8")).get("name") or folder.name
            except (OSError, ValueError):
                continue
            out.append({"project": folder.name, "name": name, "build": build.name,
                        "built_at": datetime.fromtimestamp(build.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                        "added": folder.name in added})
        return out

    def _all_metas(self) -> List[Dict]:
        if not self.dir.is_dir():
            return []
        out = []
        for p in self.dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return out

    def add_fontmaker(self, project: str) -> Dict:
        if not _PROJECT.match(project or "") or not (self.fontmaker_dir / project / "font.json").is_file():
            raise FontNotFound(project)
        build = self._latest_build(project)
        if build is None:
            raise FontError("This Font Maker font has no build yet: build it in Font Maker first.")
        inspect(build.read_bytes())
        font_id = f"fm-{project}"
        if not (self.dir / f"{font_id}.json").is_file():
            name = json.loads((self.fontmaker_dir / project / "font.json").read_text(encoding="utf-8")).get("name")
            self._write_meta({"id": font_id, "name": name or project, "source": "fontmaker", "project": project,
                              "added_at": _now()})
        return self.get(font_id)

    def set_size(self, font_id: str, size: float) -> Dict:
        """Your size for a font (A- / A+), on top of the size matched to the normal fonts: 1 = as matched."""
        meta = self._meta(font_id)
        meta["size"] = round(min(MAX_SIZE, max(MIN_SIZE, float(size))), 2)
        self._write_meta(meta)
        return self.get(font_id)

    def remove(self, font_id: str) -> None:
        """Remove a font from the tabs: an upload's file too; a Font Maker font's reference only."""
        meta = self._meta(font_id)
        if meta.get("source") != "fontmaker" and meta.get("file"):
            (self.dir / meta["file"]).unlink(missing_ok=True)
        (self.dir / f"{font_id}.json").unlink(missing_ok=True)

    def for_word(self, font_id: str) -> Tuple[str, Optional[bytes]]:
        """The family name for a Word file, and the font's bytes when it may be embedded (else None)."""
        info = self.info(font_id)
        return info.family, self.path(font_id).read_bytes() if info.embeddable else None
