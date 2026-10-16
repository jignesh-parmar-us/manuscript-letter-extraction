"""What the line-search reader's training keeps between trainings (docs/SPEED_PLAN.md, S3), in the book folder's
`line-search/features/`. A cache: deleting the folder is always safe, it is built again; it holds no labels.

- **MaskPack** (S3c): every letter mask the training opens, from one file instead of a PNG per letter. A mask is
  read again when its file changed (path, size or time); `digest` is a hash of its content.
- **FeatureStore** (S3a): each training letter's feature rows (`linesearch._letter_rows`), with a key saying
  what they were computed from (the mask, the other letters on its line, the line spacing, the feature version,
  the seed). A row depends only on its letter, never on the fold or the labels, so a fold only picks rows and the
  labels and review status come fresh from the database. Varied copies are kept as far as they were needed.
  Rows are kept exactly: the picture part is whole numbers / 255 (8 bits), the rest 32-bit.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from PIL import Image

from ..ocr.features import FEATURE_VERSION, PIXELS

PIX = PIXELS * PIXELS                         # the picture part of a row (8-bit values / 255)


def store_folder(book_dir: Path) -> Path:
    return Path(book_dir) / "line-search" / "features"


def _replace(tmp: Path, path: Path) -> None:
    os.replace(tmp, path)


class MaskPack:
    """Letter masks by sample, from `masks.npz`, each read again from its PNG when the file changed.
    `folder_of(book id)`: the folder of a sample's own row, when the pack also holds letters of another row (a
    book's pack holds its dataset's letters too, C20); without it every mask is in `book_dir`."""

    def __init__(self, book_dir: Path, folder_of: Optional[Callable[[int], Path]] = None):
        self.book_dir = Path(book_dir)
        self.folder_of = folder_of
        self.path = store_folder(book_dir) / "masks.npz"
        self.masks: Dict[int, np.ndarray] = {}
        self.stamp: Dict[int, tuple] = {}         # sample id -> (mask path, size, mtime_ns)
        self.hash: Dict[int, str] = {}
        self.read = 0                             # PNGs opened (tests)
        self.dirty = False
        try:
            with np.load(self.path) as z:
                ids, shapes, offs, bits = z["ids"], z["shapes"], z["offs"], z["bits"]
                paths, sizes, times, hashes = z["paths"], z["sizes"], z["times"], z["hashes"]
            for k, sid in enumerate(ids.tolist()):
                h, w = (int(v) for v in shapes[k])
                self.masks[sid] = np.unpackbits(bits[offs[k]:offs[k + 1]], count=h * w).reshape(h, w).astype(bool)
                self.stamp[sid] = (str(paths[k]), int(sizes[k]), int(times[k]))
                self.hash[sid] = str(hashes[k])
        except (OSError, KeyError, ValueError):
            self.masks, self.stamp, self.hash = {}, {}, {}

    def get(self, smp) -> np.ndarray:
        """The sample's mask (bool), as `samples._sample_mask` reads it."""
        if not smp.mask:
            from .samples import _sample_mask
            return _sample_mask(None, None, smp)               # raises: no mask
        f = (self.folder_of(smp.book_id) if self.folder_of else self.book_dir) / smp.mask
        st = f.stat()
        stamp = (smp.mask, st.st_size, st.st_mtime_ns)
        if self.stamp.get(smp.id) != stamp:
            with Image.open(f) as im:
                m = np.asarray(im.convert("L")) > 127
            self.read += 1
            self.masks[smp.id], self.stamp[smp.id] = m, stamp
            self.hash[smp.id] = hashlib.sha1(np.packbits(m).tobytes() + str(m.shape).encode()).hexdigest()
            self.dirty = True
        return self.masks[smp.id]

    def digest(self, sid: int) -> str:
        return self.hash[sid]

    def save(self) -> None:
        if not self.dirty:
            return
        ids = sorted(self.masks)
        packed = [np.packbits(self.masks[i]) for i in ids]
        offs = np.concatenate([[0], np.cumsum([len(p) for p in packed])]).astype(np.int64)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name("masks.tmp.npz")
        np.savez(tmp, ids=np.array(ids, np.int64), shapes=np.array([self.masks[i].shape for i in ids], np.int32).reshape(-1, 2),
                 offs=offs, bits=np.concatenate(packed) if packed else np.zeros(0, np.uint8),
                 paths=np.array([self.stamp[i][0] for i in ids], dtype=str),
                 sizes=np.array([self.stamp[i][1] for i in ids], np.int64),
                 times=np.array([self.stamp[i][2] for i in ids], np.int64),
                 hashes=np.array([self.hash[i] for i in ids], dtype=str))
        _replace(tmp, self.path)
        self.dirty = False


class Entry:
    """One letter's rows: `base` (its picture, its window, the two small shifts: those that exist), `negs` ("not a
    letter" pieces) and `varied` (its varied copies 0, 1, ...)."""
    __slots__ = ("key", "base", "negs", "varied")

    def __init__(self, key: str, base: List[np.ndarray], negs: List[np.ndarray], varied: List[np.ndarray]):
        self.key, self.base, self.negs, self.varied = key, base, negs, varied


class FeatureStore:
    """Each training letter's rows by sample id (see the module notes), kept in `rows.npz` + `keys.json`."""

    def __init__(self, book_dir: Path):
        self.folder = store_folder(book_dir)
        self.entries: Dict[int, Entry] = {}
        self.computed = 0                         # letters whose base rows were computed (tests)
        self.copies = 0                           # varied copies computed (tests)
        self.dirty = False
        try:
            keys = json.loads((self.folder / "keys.json").read_text(encoding="utf-8"))
            if keys.get("version") != FEATURE_VERSION:
                raise ValueError("another feature version")
            with np.load(self.folder / "rows.npz") as z:
                sid, kind, pix, rest, stamp = z["sid"], z["kind"], z["pix"], z["rest"], str(z["stamp"])
            if len(sid) != keys["rows"] or stamp != keys.get("stamp"):
                raise ValueError("rows and keys do not match")
            X = np.concatenate([pix.astype(np.float32) / 255.0, rest], axis=1) if len(sid) else np.zeros((0, 0), np.float32)
            for s, k in keys["keys"].items():
                self.entries[int(s)] = Entry(k, [], [], [])
            for r, (s, kd) in enumerate(zip(sid.tolist(), kind.tolist())):
                e = self.entries[s]
                (e.base if kd == 0 else e.negs if kd == 1 else e.varied).append(X[r])
        except (OSError, KeyError, ValueError):
            self.entries = {}

    def get(self, sid: int, key: str) -> Optional[Entry]:
        e = self.entries.get(sid)
        return e if e is not None and e.key == key else None

    def put(self, sid: int, entry: Entry) -> None:
        self.entries[sid] = entry
        self.dirty = True

    def keep_only(self, sids) -> None:
        """Forget the letters no longer trained on (deleted, recut): the store does not grow for ever."""
        gone = set(self.entries) - set(sids)
        for s in gone:
            del self.entries[s]
        self.dirty = self.dirty or bool(gone)

    def save(self) -> None:
        if not self.dirty:
            return
        sid, kind, rows = [], [], []
        for s in sorted(self.entries):
            e = self.entries[s]
            for kd, part in ((0, e.base), (1, e.negs), (2, e.varied)):
                for r in part:
                    sid.append(s)
                    kind.append(kd)
                    rows.append(r)
        X = np.array(rows, np.float32).reshape(len(rows), -1)
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / "rows.tmp.npz"
        stamp = uuid.uuid4().hex                  # rows and keys written together (a crash between: both dropped)
        np.savez(tmp, stamp=np.array(stamp), sid=np.array(sid, np.int64), kind=np.array(kind, np.int8),
                 pix=np.rint(X[:, :PIX] * 255.0).astype(np.uint8), rest=X[:, PIX:])
        _replace(tmp, self.folder / "rows.npz")
        keys = {"version": FEATURE_VERSION, "rows": len(sid), "stamp": stamp, "keys": {str(s): e.key for s, e in self.entries.items()}}
        (self.folder / "keys.tmp.json").write_text(json.dumps(keys), encoding="utf-8")
        _replace(self.folder / "keys.tmp.json", self.folder / "keys.json")
        self.dirty = False
