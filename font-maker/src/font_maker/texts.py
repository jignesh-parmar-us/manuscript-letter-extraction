"""Test texts (F7): fixed texts the font is measured on after every build.

  - **Yours:** texts you save on the Try it tab, kept in the font project (`texts.json`: id, name, text).
  - **Hand-checked lines** of each of the font's books (Read Book → Line truth, `line_truth`), read-only, in
    page and line order. They come from the same pages as the groups, so they flatter the font a little;
    your own texts (another edition, a letter) show the gaps new text has.

`coverage` counts, per text, what the newest build draws as the book's own, pieced, filled or missing
(tryit.classify), with the build before it (each build keeps its report next to its .ttf), and the most
frequent aksharas that are not the book's own.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy import select

from letter_extractor.app.db import Book, Line, LineTruth, Page

from .projects import ProjectError, Projects
from .store import Store
from .tryit import classify

MAX_TEXT = 200_000


class Texts:
    def __init__(self, store: Store, projects: Projects):
        self.store, self.projects = store, projects

    def _path(self, font_id: str):
        return self.projects.dir / font_id / "texts.json"

    def yours(self, font_id: str) -> List[Dict]:
        self.projects.get(font_id)
        path = self._path(font_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def truth(self, sources: List[int]) -> List[Dict]:
        out = []
        with self.store.session() as s:
            for book_id in sources:
                book = s.get(Book, book_id)
                rows = s.execute(select(LineTruth.text_dev).join(Line, Line.id == LineTruth.line_id)
                                 .join(Page, Page.id == Line.page_id).where(Page.book_id == book_id)
                                 .order_by(Page.number, Page.id, Line.number)).scalars().all()
                lines = [r.strip() for r in rows if r and r.strip()]
                if book and lines:
                    out.append({"id": f"truth-{book_id}", "name": f"Hand-checked lines of {book.name}",
                                "text": "\n".join(lines), "source": "truth", "lines": len(lines)})
        return out

    def list(self, font_id: str) -> List[Dict]:
        font = self.projects.get(font_id)
        return self.truth(font["sources"]) + [{**t, "source": "yours"} for t in self.yours(font_id)]

    def save(self, font_id: str, name: str, text: str, text_id: Optional[str] = None) -> Dict:
        name = " ".join((name or "").split())[:100]
        if not name:
            raise ProjectError("The test text needs a name.")
        if not text.strip():
            raise ProjectError("The test text is empty.")
        if len(text) > MAX_TEXT:
            raise ProjectError(f"The test text is longer than {MAX_TEXT} characters.")
        texts = self.yours(font_id)
        if text_id is None:
            used = [int(m.group(1)) for t in texts if (m := re.match(r"t(\d+)$", t["id"]))]
            text_id = f"t{max(used, default=0) + 1}"
            texts.append({"id": text_id, "name": name, "text": text})
        else:
            hit = next((t for t in texts if t["id"] == text_id), None)
            if hit is None:
                raise ProjectError(f"No test text {text_id}.")
            hit.update(name=name, text=text)
        self._write(font_id, texts)
        return {"id": text_id, "name": name, "text": text, "source": "yours"}

    def delete(self, font_id: str, text_id: str) -> None:
        texts = self.yours(font_id)
        if not any(t["id"] == text_id for t in texts):
            raise ProjectError(f"No test text {text_id} of yours (hand-checked lines cannot be deleted here).")
        self._write(font_id, [t for t in texts if t["id"] != text_id])

    def _write(self, font_id: str, texts: List[Dict]) -> None:
        path = self._path(font_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(texts, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def coverage(self, font_id: str, reports: List[Dict]) -> List[Dict]:
        """Per test text: counts with the newest report and the one before (`reports`: newest first)."""
        out = []
        for t in self.list(font_id):
            row = {"id": t["id"], "name": t["name"], "source": t["source"], "builds": []}
            for k, report in enumerate(reports[:2]):
                counts: Counter = Counter()
                gaps: Counter = Counter()
                for a in classify(t["text"], report)["aksharas"]:
                    if a["kind"] in ("space", "other"):
                        continue
                    counts[a["kind"]] += 1
                    if a["kind"] != "book":
                        gaps[a["text"]] += 1
                build = {"build": report.get("build"), "aksharas": sum(counts.values()), **counts}
                if k == 0:
                    build["gaps"] = gaps.most_common(20)
                row["builds"].append(build)
            out.append(row)
        return out
