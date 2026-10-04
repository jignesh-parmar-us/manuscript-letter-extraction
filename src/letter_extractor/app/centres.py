"""Group centres and distances from the stored fingerprints (C5c).

A group's centre is the unit-length mean of its members' fingerprints, as in grouping.py (C4); a
sample's `distance` is its distance to that centre. Both are recomputed whenever a group changes,
so "nearest to the centre first" and the suggestions stay correct after manual review.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import LetterGroup, Sample


def _vec(blob: Optional[bytes]) -> Optional[np.ndarray]:
    return None if blob is None else np.frombuffer(blob, np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-9)


def members(s: Session, group_id: int) -> List[Sample]:
    return list(s.scalars(select(Sample).where(Sample.group_id == group_id, Sample.deleted.is_(False))))


def recompute(s: Session, group_ids: Iterable[int]) -> None:
    """New centre and member distances for each group (groups that no longer exist are skipped)."""
    for gid in set(group_ids):
        if gid is None or s.get(LetterGroup, gid) is None:
            continue
        mem = [m for m in members(s, gid) if m.fingerprint is not None]
        if not mem:
            continue
        X = np.stack([_vec(m.fingerprint) for m in mem])
        c = _unit(X.mean(axis=0))
        for m, d in zip(mem, np.linalg.norm(X - c, axis=1)):
            m.distance = float(d)


def centres(s: Session, book_id: int, labelled_only: bool = False) -> Tuple[List[LetterGroup], np.ndarray]:
    """All groups of a book with members, and their centres (one row each)."""
    q = select(LetterGroup).where(LetterGroup.book_id == book_id)
    if labelled_only:
        q = q.where(LetterGroup.label_dev != "")
    groups, rows = [], []
    for g in s.scalars(q.order_by(LetterGroup.id)):
        fps = [_vec(m.fingerprint) for m in members(s, g.id) if m.fingerprint is not None]
        if fps:
            groups.append(g)
            rows.append(_unit(np.stack(fps).mean(axis=0)))
    return groups, (np.stack(rows) if rows else np.zeros((0, 0), np.float32))


def suggestions(s: Session, book_id: int, samples: List[Sample], max_distance: float) -> Dict[int, Dict]:
    """For each sample, the nearest group whose centre is within `max_distance` (labelled groups
    preferred: a labelled group wins if it is at most 10% further away than the nearest one)."""
    groups, C = centres(s, book_id)
    out: Dict[int, Dict] = {}
    if not groups:
        return out
    labelled = np.array([g.label_dev != "" for g in groups])
    for smp in samples:
        v = _vec(smp.fingerprint)
        if v is None:
            continue
        d = np.linalg.norm(C - v, axis=1)
        if smp.group_id is not None:                       # never suggest its own group
            d = np.where(np.array([g.id == smp.group_id for g in groups]), np.inf, d)
        j = int(np.argmin(d))
        if labelled.any():
            jl = int(np.argmin(np.where(labelled, d, np.inf)))
            if d[jl] <= 1.1 * d[j]:
                j = jl
        if d[j] <= max_distance:
            g = groups[j]
            out[smp.id] = {"group_id": g.id, "code": g.code, "label_dev": g.label_dev, "label_guj": g.label_guj,
                           "distance": round(float(d[j]), 3)}
    return out
