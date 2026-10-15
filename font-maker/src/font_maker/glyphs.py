"""Glyph images (F2): one cleaned, enlarged image per letter group, from the group's best copies.

How a glyph is made (font-maker/docs/FONT_PLAN.md, section 3, steps 1-5):
  - the groups of the font's books with the chosen statuses and a label of exactly one akshara
    (a label of several aksharas is a cut error: listed, not made);
  - the group's copies, closest to the group's centre first (`sample.distance`); the best N (`copies`).
    Only copies cut from a page are used when the group has any; letters made by the reading app's
    "Generate missing letters" (source "generated") only when it has none, and that glyph is marked
    `generated` (made by the system), as anything system-made is always shown;
  - the ink of each copy (its mask), aligned on the ink's centre (shift only), averaged, enlarged x4 and
    thresholded: the **system pick**. When the copies disagree (median overlap of each pair below `min_agree`), the
    single best copy is used instead;
  - **your pick**: one chosen copy instead of the system pick; or the group **left out**.

Kept fast (section 5, F2): each glyph has a fingerprint made from ids, labels and settings only (no image
is opened to make it). `glyphs/glyphs.json` keeps the glyphs with their fingerprints; it is read once per
font and then kept in memory. Opening a font remakes only the glyphs whose fingerprint changed; a click
remakes only that glyph. Image files carry the fingerprint in their name, so a browser may cache them.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from sqlalchemy import select

from letter_extractor.app.db import GENERATED, Book, LetterGroup, Sample
from letter_extractor.ocr.aksharas import split_aksharas

from .metrics import Lines, estimate, measure
from .projects import ProjectError, Projects
from .store import Store
from .trace import svg_path, trace

ALGO = 2                    # raise when the way a glyph is made changes: every glyph is then remade
                            # (2: glyphs keep their copies' ink boxes, for F3)
SCALE = 4                   # enlargement before thresholding (smooth edges for tracing, F4)
KINDS = ("letter", "danda", "digit")
DEFAULTS = {"copies": 8, "min_agree": 0.6}


# ---- the image steps ----------------------------------------------------------------------------------
def crop(ink: np.ndarray) -> np.ndarray:
    """The ink's bounding box (an empty image stays 1x1)."""
    ys, xs = np.nonzero(ink)
    if not len(ys):
        return np.zeros((1, 1), bool)
    return ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def align(inks: Sequence[np.ndarray]) -> np.ndarray:
    """The cropped inks on one canvas, each with its ink centre on the canvas centre (shift only)."""
    crops = [crop(i) for i in inks]
    h = max(c.shape[0] for c in crops) + 2
    w = max(c.shape[1] for c in crops) + 2
    out = np.zeros((len(crops), h, w), np.float32)
    for k, c in enumerate(crops):
        ys, xs = np.nonzero(c)
        cy, cx = (ys.mean(), xs.mean()) if len(ys) else (0.0, 0.0)
        y0 = int(round(h / 2 - cy - 0.5))
        x0 = int(round(w / 2 - cx - 0.5))
        y0 = min(max(y0, 0), h - c.shape[0])
        x0 = min(max(x0, 0), w - c.shape[1])
        out[k, y0:y0 + c.shape[0], x0:x0 + c.shape[1]] = c
    return out


def enlarge(img: np.ndarray) -> np.ndarray:
    """x SCALE with smooth edges, then back to ink / no ink."""
    a = img.astype(np.float32)
    big = cv2.resize(a, (a.shape[1] * SCALE, a.shape[0] * SCALE), interpolation=cv2.INTER_CUBIC)
    return crop(big >= 0.5)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 1.0


def ink_box(ink: np.ndarray) -> List[int]:
    """[top, bottom, left, right] of the ink inside its sample box (bottom and right exclusive), for F3."""
    ys, xs = np.nonzero(ink)
    if not len(ys):
        return [0, int(ink.shape[0]), 0, int(ink.shape[1])]
    return [int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1]


def make_image(inks: Sequence[np.ndarray], min_agree: float) -> Tuple[np.ndarray, str, float]:
    """(enlarged ink, "average" | "copy", agreement) from the copies, best first."""
    if len(inks) == 1:
        return enlarge(crop(inks[0])), "copy", 1.0
    stack = align(inks) > 0.5
    # how much the copies agree: the median overlap of every pair (with only two copies, a comparison
    # with their average would always look good, as the average then holds both shapes)
    agree = float(np.median([iou(stack[i], stack[j]) for i in range(len(stack)) for j in range(i + 1, len(stack))]))
    mean = stack.mean(axis=0)
    if agree < min_agree:
        return enlarge(crop(inks[0])), "copy", agree
    return enlarge(mean), "average", agree


def read_ink(book_dir: Path, mask: str, image: str) -> np.ndarray:
    """The copy's ink: its mask (255 = ink), else the image's dark pixels (Otsu)."""
    if mask:
        m = cv2.imread(str(book_dir / mask), cv2.IMREAD_GRAYSCALE)
        if m is not None:
            return m > 127
    g = cv2.imread(str(book_dir / image), cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise FileNotFoundError(book_dir / image)
    _, ink = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink > 0


# ---- the groups of a font, from the library (one query each, no images) -----------------------------------
@dataclass
class Group:
    id: int
    book_id: int
    book_dir: Path
    code: str
    kind: str
    status: str
    label_dev: str
    label_guj: str
    copies: List[Tuple[int, str, str]] = field(default_factory=list)   # (sample id, mask, image), best first
    generated: set = field(default_factory=set)                         # ids of copies made by the system

    def best(self, n: int) -> Tuple[List[Tuple[int, str, str]], bool]:
        """The best n copies cut from a page; only when there is none, the best made by the system."""
        real = [c for c in self.copies if c[0] not in self.generated]
        return (real[:n], False) if real else (self.copies[:n], True)


def load_groups(store: Store, sources: List[int], statuses: List[str]) -> Tuple[Dict[int, Group], List[Dict]]:
    """The groups that can become glyphs (by id), and the cut errors (labels of several aksharas)."""
    with store.session() as s:
        rows = s.execute(select(LetterGroup, Book.folder).join(Book, Book.id == LetterGroup.book_id)
                         .where(LetterGroup.book_id.in_(sources), LetterGroup.status.in_(statuses),
                                LetterGroup.kind.in_(KINDS), LetterGroup.label_dev != "")
                         .order_by(LetterGroup.book_id, LetterGroup.code)).all()
        groups: Dict[int, Group] = {}
        cut_errors: List[Dict] = []
        for g, folder in rows:
            if len(split_aksharas(g.label_dev)) != 1:
                cut_errors.append({"group": g.id, "code": g.code, "label_dev": g.label_dev, "label_guj": g.label_guj})
                continue
            groups[g.id] = Group(g.id, g.book_id, store.root / "books" / folder, g.code, g.kind, g.status,
                                 g.label_dev, g.label_guj)
        if groups:
            samples = s.execute(select(Sample.id, Sample.group_id, Sample.mask, Sample.image, Sample.source)
                                .where(Sample.group_id.in_(list(groups)), Sample.deleted.is_(False))
                                .order_by(Sample.group_id, Sample.distance.is_(None), Sample.distance, Sample.id)).all()
            for sid, gid, mask, image, source in samples:
                groups[gid].copies.append((sid, mask, image))
                if source == GENERATED:
                    groups[gid].generated.add(sid)
    return {k: g for k, g in groups.items() if g.copies}, cut_errors


def fingerprint(g: Group, pick: Optional[int], settings: Dict) -> str:
    used = [pick] if pick else [c[0] for c in g.best(settings["copies"])[0]]
    key = [ALGO, g.id, g.label_dev, used, settings["copies"], settings["min_agree"]]
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()[:12]


# ---- one font's glyphs, kept in memory ------------------------------------------------------------------
class Busy(ProjectError):
    """The glyphs of this font are being made; try again when that is done."""


class GlyphMaker:
    """The glyphs of every open font: loaded once from `glyphs.json`, then kept in memory (see the top)."""

    def __init__(self, store: Store, projects: Projects):
        self.store, self.projects = store, projects
        self.fonts: Dict[str, Dict] = {}      # font id -> {"glyphs": {group id: glyph}, "cut_errors", "lost", "metrics"}
        self.lines: Dict[str, Lines] = {}     # font id -> its measured lines (F3), in memory only
        self.jobs: Dict[str, Dict] = {}       # font id -> {"running", "done", "total", "error"}
        self.lock = threading.Lock()
        self.made = 0                         # glyph images made since start (counted by the tests)
        self.traced = 0                       # outlines traced since start (F4, counted by the tests)

    def _dir(self, font_id: str) -> Path:
        return self.projects.dir / font_id / "glyphs"

    def _loaded(self, font_id: str) -> Dict:
        if font_id not in self.fonts:
            path = self._dir(font_id) / "glyphs.json"
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            self.fonts[font_id] = {"glyphs": {int(k): v for k, v in data.get("glyphs", {}).items()},
                                   "cut_errors": data.get("cut_errors", []), "lost": data.get("lost", []),
                                   "metrics": data.get("metrics", {})}
        return self.fonts[font_id]

    def _save(self, font_id: str) -> None:
        state = self.fonts[font_id]
        folder = self._dir(font_id)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "glyphs.json.tmp"
        tmp.write_text(json.dumps({"glyphs": {str(k): v for k, v in state["glyphs"].items()},
                                   "cut_errors": state["cut_errors"], "lost": state["lost"],
                                   "metrics": state["metrics"]},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / "glyphs.json")

    def _remove(self, font_id: str, image: str) -> None:
        """A glyph image that is no longer used, with its outline (F4)."""
        folder = self._dir(font_id)
        (folder / image).unlink(missing_ok=True)
        (folder / (image + ".outline.json")).unlink(missing_ok=True)

    def forget(self, font_id: str) -> None:
        """The font was deleted: drop what is kept in memory."""
        self.fonts.pop(font_id, None)
        self.jobs.pop(font_id, None)
        self.lines.pop(font_id, None)

    # -- what is shown ----------------------------------------------------------------------------------
    def state(self, font_id: str) -> Dict:
        self.projects.get(font_id)                               # 404 for an unknown font
        st = self._loaded(font_id)
        job = self.jobs.get(font_id, {"running": False, "done": 0, "total": 0, "error": None})
        return {"job": dict(job), "glyphs": list(st["glyphs"].values()), "cut_errors": st["cut_errors"],
                "lost": st["lost"], "metrics": st["metrics"]}

    def _check_busy(self, font_id: str) -> None:
        if self.jobs.get(font_id, {}).get("running"):
            raise Busy("The glyphs are still being made. Try again when that is done.")

    # -- making the glyphs ----------------------------------------------------------------------------------
    def _plan(self, font_id: str):
        font = self.projects.get(font_id)
        settings = {**DEFAULTS, **font.get("settings", {})}
        groups, cut_errors = load_groups(self.store, font["sources"], font["statuses"])
        picks: Dict[str, Dict] = font.get("picks") or {}
        left_out = font.get("left_out") or {}
        if isinstance(left_out, list):                           # fonts made before F2
            left_out = {}
        lost = []
        for key, p in picks.items():
            g = groups.get(int(key))
            if g is None or p["sample"] not in {c[0] for c in g.copies}:
                lost.append({**p, "reason": "the group is gone or no longer used" if g is None
                             else "the copy was deleted or moved to another group"})
        lost_groups = {p["group"] for p in lost}
        return font, settings, groups, cut_errors, picks, left_out, lost, lost_groups

    def _glyph(self, font_id: str, g: Group, pick: Optional[int], settings: Dict, old: Optional[Dict],
               left_out: bool, lost: bool) -> Dict:
        fp = fingerprint(g, pick, settings)
        folder = self._dir(font_id)
        if old and old.get("fp") == fp and (folder / old["image"]).is_file():
            glyph = dict(old)
        else:
            if pick:
                (sid, mask, image), = [c for c in g.copies if c[0] == pick]
                inks = {pick: read_ink(g.book_dir, mask, image)}
                img, method, agree = enlarge(crop(inks[pick])), "pick", 1.0
                generated = pick in g.generated
            else:
                best, generated = g.best(settings["copies"])
                inks = {sid: read_ink(g.book_dir, m, i) for sid, m, i in best}
                img, method, agree = make_image(list(inks.values()), settings["min_agree"])
                if method == "copy":
                    inks = {best[0][0]: inks[best[0][0]]}
            used = list(inks)
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{g.book_id}-{g.code}-{fp}.png"
            cv2.imwrite(str(folder / name), np.where(img, 0, 255).astype(np.uint8))
            if old and old.get("image") and old["image"] != name:
                self._remove(font_id, old["image"])
            self.made += 1
            glyph = {"fp": fp, "image": name, "method": method, "agree": round(agree, 3), "used": used,
                     "size": [int(img.shape[1]), int(img.shape[0])],
                     "ink": {str(sid): ink_box(ink) for sid, ink in inks.items()}, "generated": generated}
        glyph.update({"group": g.id, "book": g.book_id, "code": g.code, "kind": g.kind, "status": g.status,
                      "label_dev": g.label_dev, "label_guj": g.label_guj, "count": len(g.copies),
                      "left_out": left_out, "lost": lost})
        return glyph

    def refresh(self, font_id: str, progress=None) -> int:
        """Bring the font's glyphs up to date; returns how many images were made (0 when nothing changed)."""
        font, settings, groups, cut_errors, picks, left_out, lost, lost_groups = self._plan(font_id)
        st = self._loaded(font_id)
        lines = self.lines[font_id] = measure(self.store, font["sources"])          # F3: no images, one query
        before, out = self.made, {}
        for n, g in enumerate(groups.values(), 1):
            pick = picks.get(str(g.id), {}).get("sample") if g.id not in lost_groups else None
            out[g.id] = self._glyph(font_id, g, pick, settings, st["glyphs"].get(g.id), str(g.id) in left_out,
                                    g.id in lost_groups)
            out[g.id].update(lines.place(out[g.id].get("ink", {})))
            if progress:
                progress(n, len(groups))
        estimate(list(out.values()), SCALE)                      # glyphs made only from generated letters
        for gid, old in st["glyphs"].items():                    # groups no longer in the font
            if gid not in out and old.get("image"):
                self._remove(font_id, old["image"])
        changed = (out, cut_errors, lost, lines.summary) != (st["glyphs"], st["cut_errors"], st["lost"], st["metrics"])
        st.update(glyphs=out, cut_errors=cut_errors, lost=lost, metrics=lines.summary)
        if changed or not (self._dir(font_id) / "glyphs.json").is_file():
            self._save(font_id)                                  # nothing changed: no file is written
        return self.made - before

    def start(self, font_id: str) -> Dict:
        """Opening a font: remake what changed, in the background when there is anything to make."""
        with self.lock:
            if self.jobs.get(font_id, {}).get("running"):
                return self.state(font_id)
            job = {"running": True, "done": 0, "total": 0, "error": None}
            self.jobs[font_id] = job

        def step(done: int, total: int):
            job["done"], job["total"] = done, total

        def run():
            try:
                self.refresh(font_id, step)
            except Exception as e:                               # shown on the screen
                job["error"] = str(e)
            finally:
                job["running"] = False

        threading.Thread(target=run, name=f"glyphs-{font_id}", daemon=True).start()
        return self.state(font_id)

    # -- your choice for one group ---------------------------------------------------------------------------
    def choose(self, font_id: str, group_id: int, choice: str, sample: Optional[int] = None) -> Dict:
        """choice: "system" (forget your pick and "left out"), "copy" (use `sample`), "left_out", "keep"."""
        self._check_busy(font_id)
        font, settings, groups, _, picks, left_out, lost, lost_groups = self._plan(font_id)
        g = groups.get(group_id)
        label = g.label_dev if g else next((p["label"] for p in lost if p["group"] == group_id), "")
        if choice == "copy":
            if g is None or sample not in {c[0] for c in g.copies}:
                raise ProjectError("That copy is not in this group (any more).")
            picks[str(group_id)] = {"group": group_id, "label": label, "sample": sample}
        elif choice == "system":
            picks.pop(str(group_id), None)
            left_out.pop(str(group_id), None)
        elif choice == "left_out":
            left_out[str(group_id)] = {"group": group_id, "label": label}
        elif choice == "keep":
            left_out.pop(str(group_id), None)
        else:
            raise ProjectError(f"Unknown choice: {choice}.")
        if group_id in lost_groups and choice != "copy":
            picks.pop(str(group_id), None)                       # a lost pick is forgotten once you choose again
        self.projects.set_choices(font_id, picks, left_out)
        st = self._loaded(font_id)
        st["lost"] = [p for p in lost if p["group"] != group_id]
        if g is not None:
            pick = picks.get(str(group_id), {}).get("sample")
            glyph = self._glyph(font_id, g, pick, settings, st["glyphs"].get(group_id), str(group_id) in left_out, False)
            lines = self.lines.get(font_id) or measure(self.store, font["sources"])
            self.lines[font_id] = lines
            glyph.update(lines.place(glyph.get("ink", {})))
            st["glyphs"][group_id] = glyph
            estimate(list(st["glyphs"].values()), SCALE)
        self._save(font_id)
        return {"glyph": st["glyphs"].get(group_id), "lost": st["lost"]}

    def outline(self, font_id: str, group_id: int) -> Dict:
        """The glyph's outline (F4): traced the first time it is asked for, then read from its file."""
        glyph = self._loaded(font_id)["glyphs"].get(group_id)
        if glyph is None:
            raise ProjectError(f"Group {group_id} has no glyph in this font.")
        return {"contours": self.contours(font_id, glyph), "size": [glyph["size"][0] / SCALE, glyph["size"][1] / SCALE]}

    def contours(self, font_id: str, glyph: Dict) -> List[Dict]:
        folder = self._dir(font_id)
        path = folder / (glyph["image"] + ".outline.json")
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        img = cv2.imread(str(folder / glyph["image"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ProjectError(f"The image of {glyph['label_dev']} is missing; open the Glyphs tab to make it again.")
        contours = trace(img < 128, SCALE)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(contours), encoding="utf-8")
        os.replace(tmp, path)
        self.traced += 1
        return contours

    def svg(self, font_id: str, group_id: int) -> Dict:
        out = self.outline(font_id, group_id)
        return {"d": svg_path(out["contours"]), "size": out["size"], "contours": len(out["contours"])}

    def copies(self, font_id: str, group_id: int, limit: int = 120) -> List[Dict]:
        """A group's copies, best first, to pick one from (their images are the library's files)."""
        font = self.projects.get(font_id)
        with self.store.session() as s:
            g = s.get(LetterGroup, group_id)
            if g is None or g.book_id not in font["sources"]:
                raise ProjectError(f"Group {group_id} is not in this font's book.")
            rows = s.execute(select(Sample.id, Sample.image, Sample.source)
                             .where(Sample.group_id == group_id, Sample.deleted.is_(False))
                             .order_by(Sample.source == GENERATED, Sample.distance.is_(None), Sample.distance, Sample.id)
                             .limit(limit)).all()
            return [{"id": sid, "book": g.book_id, "image": image, "generated": source == GENERATED}
                    for sid, image, source in rows]
