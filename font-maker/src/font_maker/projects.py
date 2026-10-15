"""Font projects (F1): one folder per font in `<library>/fonts/`, its choices in `font.json`.

```
<library>/fonts/f0001/
  font.json     name, sources (book ids), group statuses, choices (F2-F5), build number
  builds/       the built fonts (F5)
```

The folder is named by a fixed id, so renaming a font never moves it. Deleting removes only that folder;
the library database is never touched (it is opened read-only, store.py).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Group statuses a font can take its glyphs from. "labelled": reviewed and labelled (the default);
# "auto": not reviewed, with a suggested label. A "reviewed" group has no label, so it cannot be a glyph.
STATUSES = ("labelled", "auto")
DEFAULT_STATUSES = ["labelled"]
MAX_NAME = 100
_ID = re.compile(r"^f\d{4}$")


class ProjectError(Exception):
    """A problem the user can fix (shown as a message)."""


class ProjectNotFound(ProjectError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ProjectError("The font needs a name.")
    if len(name) > MAX_NAME:
        raise ProjectError(f"The name is longer than {MAX_NAME} characters.")
    return name


def _clean_statuses(statuses: Iterable[str]) -> List[str]:
    chosen = [s for s in STATUSES if s in set(statuses)]
    unknown = set(statuses) - set(STATUSES)
    if unknown:
        raise ProjectError(f"Unknown group status: {', '.join(sorted(unknown))}. Use: {', '.join(STATUSES)}.")
    if not chosen:
        raise ProjectError("Choose at least one group status.")
    return chosen


class Projects:
    def __init__(self, fonts_dir: Path):
        self.dir = Path(fonts_dir)

    def _folder(self, font_id: str) -> Path:
        if not _ID.match(font_id or "") or not (self.dir / font_id / "font.json").is_file():
            raise ProjectNotFound(f"No font {font_id}.")
        return self.dir / font_id

    def _read(self, folder: Path) -> Dict:
        data = json.loads((folder / "font.json").read_text(encoding="utf-8"))
        builds = folder / "builds"
        files = sorted(builds.glob("*.ttf"), key=lambda p: p.stat().st_mtime) if builds.is_dir() else []
        data["builds"] = len(files)
        data["last_build"] = (datetime.fromtimestamp(files[-1].stat().st_mtime, timezone.utc)
                              .isoformat(timespec="seconds") if files else None)
        return data

    def _write(self, folder: Path, data: Dict) -> None:
        keep = {k: v for k, v in data.items() if k not in ("builds", "last_build")}
        tmp = folder / "font.json.tmp"
        tmp.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / "font.json")

    def list(self) -> List[Dict]:
        if not self.dir.is_dir():
            return []
        return [self._read(p) for p in sorted(self.dir.iterdir()) if _ID.match(p.name) and (p / "font.json").is_file()]

    def get(self, font_id: str) -> Dict:
        return self._read(self._folder(font_id))

    def _check_unique(self, name: str, other_than: Optional[str] = None) -> None:
        for p in self.list():
            if p["id"] != other_than and p["name"].casefold() == name.casefold():
                raise ProjectError(f'There is already a font named "{name}".')

    def create(self, name: str, sources: List[int], statuses: Optional[List[str]] = None) -> Dict:
        name = _clean_name(name)
        if not sources:
            raise ProjectError("Choose a book.")
        self._check_unique(name)
        statuses = _clean_statuses(statuses or DEFAULT_STATUSES)     # every check before the folder is made
        used = [int(p.name[1:]) for p in self.dir.glob("f[0-9][0-9][0-9][0-9]")] if self.dir.is_dir() else []
        font_id = f"f{max(used, default=0) + 1:04d}"
        folder = self.dir / font_id
        folder.mkdir(parents=True)
        now = _now()
        self._write(folder, {
            "id": font_id, "name": name, "sources": [int(s) for s in sources],
            "statuses": statuses,
            "left_out": [], "picks": {}, "filled": [],             # choices made in F2 / F5
            "settings": {"copies": 8, "mark_filled": True},
            "build": 0, "created_at": now, "updated_at": now})
        return self.get(font_id)

    def update(self, font_id: str, name: Optional[str] = None, statuses: Optional[List[str]] = None) -> Dict:
        folder = self._folder(font_id)
        data = self._read(folder)
        if name is not None:
            data["name"] = _clean_name(name)
            self._check_unique(data["name"], other_than=font_id)
        if statuses is not None:
            data["statuses"] = _clean_statuses(statuses)
        data["updated_at"] = _now()
        self._write(folder, data)
        return self.get(font_id)

    def delete(self, font_id: str) -> None:
        folder = self._folder(font_id)
        if folder.resolve().parent != self.dir.resolve():           # never outside fonts/
            raise ProjectError(f"Font {font_id} is not in {self.dir}.")
        shutil.rmtree(folder)
