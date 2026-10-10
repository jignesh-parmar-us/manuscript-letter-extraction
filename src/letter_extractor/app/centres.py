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
    wanted = {g.id: g for g in s.scalars(q)}
    # every member's fingerprint in one query (one query per group took a second on a large book)
    sums: Dict[int, np.ndarray] = {}
    counts: Dict[int, int] = {}
    for gid, fp in s.execute(select(Sample.group_id, Sample.fingerprint)
                             .where(Sample.book_id == book_id, Sample.group_id.is_not(None),
                                    Sample.deleted.is_(False), Sample.fingerprint.is_not(None))):
        if gid in wanted:
            v = _vec(fp).astype(np.float64)
            sums[gid] = sums[gid] + v if gid in sums else v
            counts[gid] = counts.get(gid, 0) + 1
    groups = [wanted[gid] for gid in sorted(sums)]
    rows = [_unit((sums[g.id] / counts[g.id]).astype(np.float32)) for g in groups]
    return groups, (np.stack(rows) if rows else np.zeros((0, 0), np.float32))


def suggestions(s: Session, book_id: int, samples: List[Sample], max_distance: float) -> Dict[int, Dict]:
    """For each sample, the nearest group whose centre is within `max_distance` (labelled groups
    preferred: a labelled group wins if it is at most 10% further away than the nearest one)."""
    groups, C = centres(s, book_id)
    out: Dict[int, Dict] = {}
    if not groups:
        return out
    labelled = np.array([g.label_dev != "" for g in groups])
    ids = np.array([g.id for g in groups])
    have = [smp for smp in samples if smp.fingerprint is not None]
    if not have:
        return out
    V = np.stack([_vec(smp.fingerprint) for smp in have]).astype(np.float64)
    Cd = C.astype(np.float64)
    # all distances at once: |v - c|^2 = |v|^2 + |c|^2 - 2 v.c
    D = np.sqrt(np.maximum((V * V).sum(axis=1)[:, None] + (Cd * Cd).sum(axis=1)[None, :] - 2 * V @ Cd.T, 0.0))
    for smp, d in zip(have, D):
        if smp.group_id is not None:                       # never suggest its own group
            d = np.where(ids == smp.group_id, np.inf, d)
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
