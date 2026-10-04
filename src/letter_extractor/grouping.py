"""Grouping identical letters across all pages (C4, FR-7).

Samples are grouped by fingerprint distance (features.py), separately for each kind (letters,
dandas, digits), so a danda never lands in a letter group. Red and black samples share groups.

The clustering is plain NumPy and needs memory for the groups, not for every pair of samples, so it
scales to batches of hundreds of pages:

1. **Leader pass:** in reading order, a sample joins the nearest group centre within
   `group_distance`, otherwise it starts a new group.
2. **Merge:** groups whose centres are closer than `group_distance` are merged (closest pair first,
   centres weighted by size), unless the merged group would no longer be compact (90% of its members
   within `group_outlier_distance` of the centre). The leader pass over-splits a letter when its
   first samples differ; the compactness check stops groups from creeping into look-alike letters.
   (Done for up to `group_max_merge` groups after the first pass.)
3. **Reassign:** every sample moves to its nearest centre. Steps 2 and 3 repeat `group_rounds` times.
4. **Unsure:** a sample further than `group_outlier_distance` from its group's centre leaves the
   group, and groups smaller than `min_group_size` are not groups: these samples go to `unsure`.

Centres are kept at unit length, like the fingerprints (see `_unit`).

Groups are numbered by size, largest first (g0001, g0002, ...), ties broken by the first sample in
reading order, so the numbering is stable when the input does not change.
"""
from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

from .config import Config

UNSURE = "unsure"


@dataclass
class Grouping:
    group_id: List[str]               # per sample: "g0001", ... or "unsure"
    distance: np.ndarray              # per sample: distance to its group centre (NaN for unsure)
    groups: Dict[str, List[int]]      # group id -> sample indices, largest group first
    unsure: List[int]


def _unit(v: np.ndarray) -> np.ndarray:
    """Scale to unit length. Centres are kept on the unit sphere like the fingerprints: the plain
    mean of many different fingerprints is a short vector that lies close to every sample, so a
    large group would keep swallowing its neighbours."""
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-9)


def _nearest(X: np.ndarray, C: np.ndarray, chunk: int = 4096):
    """Index of and distance to the nearest centre for every row of X (unit vectors)."""
    idx = np.empty(X.shape[0], np.int64)
    dist = np.empty(X.shape[0], np.float32)
    cn = (C * C).sum(axis=1)
    for s in range(0, X.shape[0], chunk):
        x = X[s:s + chunk]
        d2 = (x * x).sum(axis=1)[:, None] + cn[None, :] - 2.0 * x @ C.T
        j = np.argmin(d2, axis=1)
        idx[s:s + chunk] = j
        dist[s:s + chunk] = np.sqrt(np.maximum(d2[np.arange(j.size), j], 0.0))
    return idx, dist


def _leader(X: np.ndarray, t: float, batch: int = 1024) -> np.ndarray:
    """First pass, in batches: a sample joins the nearest existing centre within t; the samples of a
    batch that fit no centre are grouped among themselves one by one. Centres are updated after each
    batch, so most of the work is one matrix product per batch."""
    n, dim = X.shape
    labels = np.empty(n, np.int64)
    S = np.zeros((64, dim), np.float64)               # sums of members (grown by doubling)
    k = 0
    C = np.zeros((0, dim), np.float32)
    for s0 in range(0, n, batch):
        xb = X[s0:s0 + batch]
        ok = np.zeros(xb.shape[0], bool)
        if k:
            sim = xb @ C.T
            j = np.argmax(sim, axis=1)
            d = np.sqrt(np.maximum(2.0 - 2.0 * sim[np.arange(j.size), j], 0.0))
            ok = d <= t
            labels[s0:s0 + xb.shape[0]][ok] = j[ok]
            np.add.at(S, j[ok], xb[ok])
        rest = np.flatnonzero(~ok)
        N = np.zeros((rest.size, dim), np.float32)     # new centres within this batch
        m = 0
        for i in rest:
            x = xb[i]
            if m:
                d = np.sqrt(np.maximum(2.0 - 2.0 * (N[:m] @ x), 0.0))
                jj = int(np.argmin(d))
                if d[jj] <= t:
                    labels[s0 + i] = k + jj
                    S[k + jj] += x
                    N[jj] = _unit(S[k + jj])
                    continue
            while k + m >= S.shape[0]:
                S = np.vstack([S, np.zeros_like(S)])
            labels[s0 + i] = k + m
            S[k + m] = x
            N[m] = x
            m += 1
        k += m
        C = _unit(S[:k]).astype(np.float32)
    return labels


def _centres(X: np.ndarray, labels: np.ndarray):
    """Unit centres and sizes of the groups, in the order of np.unique(labels)."""
    ids, inv = np.unique(labels, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    starts = np.searchsorted(inv[order], np.arange(ids.size))
    sums = np.add.reduceat(X[order].astype(np.float64), starts, axis=0)
    sizes = np.diff(np.r_[starts, labels.size]).astype(np.float64)
    return ids, _unit(sums).astype(np.float32), sizes


def _merge(X: np.ndarray, labels: np.ndarray, t: float, radius: float, max_groups: int) -> np.ndarray:
    """Merge groups whose centres are closer than `t`, closest pairs first, as long as the merged
    group stays compact: 90% of its members within `radius` of the new centre. Without the radius
    check, groups creep from letter to look-alike letter one merge at a time and end as one big mix.

    The close pairs are found once; each is re-checked against the current (merged) centres when its
    turn comes. Returns the new label of every sample."""
    ids, C, sizes = _centres(X, labels)
    inverse = np.searchsorted(ids, labels)
    k = ids.size
    if k < 2 or k > max_groups:
        return inverse
    C = C.astype(np.float64)
    pairs_a, pairs_b, pairs_d = [], [], []
    for s0 in range(0, k, 1024):                      # close pairs, a block of rows at a time
        d = np.sqrt(np.maximum(2.0 - 2.0 * (C[s0:s0 + 1024] @ C.T), 0.0))
        r, c = np.nonzero(d <= t)
        keep = c > r + s0
        pairs_a.append(r[keep] + s0)
        pairs_b.append(c[keep])
        pairs_d.append(d[r[keep], c[keep]])
    pa, pb, pd = np.concatenate(pairs_a), np.concatenate(pairs_b), np.concatenate(pairs_d)
    order = np.argsort(pd, kind="stable")
    parent = np.arange(k)
    members = {g: np.flatnonzero(inverse == g) for g in np.unique(inverse[np.isin(inverse, np.r_[pa, pb])])}

    def find(g: int) -> int:
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    for a, b in zip(pa[order], pb[order]):
        a, b = find(int(a)), find(int(b))
        if a == b or np.linalg.norm(C[a] - C[b]) > t:
            continue
        both = np.concatenate([members[a], members[b]])
        centre = _unit((C[a] * sizes[a] + C[b] * sizes[b]) / (sizes[a] + sizes[b]))
        if np.percentile(np.linalg.norm(X[both] - centre, axis=1), 90) > radius:
            continue                                  # would not be one letter any more
        parent[b] = a
        C[a], sizes[a], members[a] = centre, sizes[a] + sizes[b], both
    return np.array([find(int(g)) for g in range(k)])[inverse]


def cluster(X: np.ndarray, cfg: Config) -> np.ndarray:
    """Cluster label for every row of X (0..k-1)."""
    if X.shape[0] == 0:
        return np.zeros(0, np.int64)
    t = cfg.group_distance
    labels = _leader(X, t)
    for _ in range(cfg.group_rounds):
        labels = _merge(X, labels, t, cfg.group_outlier_distance, cfg.group_max_merge)
        ids, C, _ = _centres(X, labels)
        j, _ = _nearest(X, C)
        labels = ids[j]
    _, labels = np.unique(labels, return_inverse=True)
    return labels


def group_samples(features: np.ndarray, kinds: Sequence[str], cfg: Config) -> Grouping:
    """Group all samples; `features` rows and `kinds` are in reading order (page, line, pos)."""
    n = features.shape[0]
    found: List[List[int]] = []
    for kind in sorted(set(kinds)):
        rows = np.flatnonzero(np.asarray(kinds) == kind)
        labels = cluster(features[rows], cfg)
        for k in range(labels.max() + 1 if labels.size else 0):
            found.append(rows[labels == k].tolist())
    found.sort(key=lambda m: (-len(m), m[0]))
    group_id = [UNSURE] * n
    distance = np.full(n, np.nan, np.float32)
    groups: Dict[str, List[int]] = {}
    unsure: List[int] = []
    kept: List[List[int]] = []
    for members in found:
        centre = _unit(features[members].mean(axis=0))
        d = np.linalg.norm(features[members] - centre, axis=1)
        inside = [m for m, dm in zip(members, d) if dm <= cfg.group_outlier_distance]
        unsure.extend(m for m, dm in zip(members, d) if dm > cfg.group_outlier_distance)
        if len(inside) < cfg.min_group_size:
            unsure.extend(inside)
        else:
            kept.append(inside)
    kept.sort(key=lambda m: (-len(m), m[0]))
    for members in kept:
        gid = f"g{len(groups) + 1:04d}"
        groups[gid] = members
        centre = _unit(features[members].mean(axis=0))
        distance[members] = np.linalg.norm(features[members] - centre, axis=1)
        for m in members:
            group_id[m] = gid
    unsure.sort()
    return Grouping(group_id=group_id, distance=distance, groups=groups, unsure=unsure)


# --------------------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------------------
_GROUP_DIR = re.compile(r"^g\d{4}$")


def _sample_name(row: Dict) -> str:
    stem = Path(row["image"]).parent.name                # letters/<page stem>/L01_003.png
    return f"{stem}_{Path(row['image']).name}"


def write_group_folders(out_dir: Path, rows: List[Dict], grouping: Grouping) -> None:
    """groups/g0001/<page>_L01_003.png ... and unsure/<page>_L01_003.png: copies of the letter images,
    so a group can be looked through in any image viewer. Folders of an earlier run are replaced."""
    out_dir = Path(out_dir)
    gdir, udir = out_dir / "groups", out_dir / UNSURE
    if gdir.is_dir():
        for d in gdir.iterdir():
            if d.is_dir() and _GROUP_DIR.match(d.name):
                shutil.rmtree(d)
    if udir.is_dir():
        for f in udir.glob("*.png"):
            f.unlink()
    for gid, members in grouping.groups.items():
        target = gdir / gid
        target.mkdir(parents=True, exist_ok=True)
        for m in members:
            shutil.copyfile(out_dir / rows[m]["image"], target / _sample_name(rows[m]))
    udir.mkdir(exist_ok=True)
    for m in grouping.unsure:
        shutil.copyfile(out_dir / rows[m]["image"], udir / _sample_name(rows[m]))


_CSS = """
:root { --bg:#faf8f5; --fg:#222; --muted:#666; --line:#e3ded6; --card:#fff; --accent:#8a3b12; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1d1c1a; --fg:#eee; --muted:#aaa; --line:#3a3733; --card:#262522; --accent:#e0915f; }
}
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 20px; }
.group { background:var(--card); border:1px solid var(--line); border-radius:8px;
         padding:10px 12px; margin:0 0 10px; }
.head { display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; margin-bottom:6px; }
.id { font-weight:600; color:var(--accent); font-variant-numeric:tabular-nums; }
.meta { color:var(--muted); font-size:13px; }
.strip { display:flex; flex-wrap:wrap; gap:6px; align-items:flex-end; }
.strip img { height:56px; background:#fff; border:1px solid var(--line); border-radius:3px; }
.more { color:var(--muted); font-size:13px; align-self:center; }
h2 { font-size:18px; margin:28px 0 8px; }
"""


def write_groups_html(out_dir: Path, rows: List[Dict], grouping: Grouping, cfg: Config) -> Path:
    """groups.html: one row per group with up to `group_max_shown` samples (nearest to the centre
    first), then the unsure samples. Works offline: images are linked relative to the output folder."""
    out_dir = Path(out_dir)

    def thumb(m: int) -> str:
        r = rows[m]
        title = f"{r['page']} line {r['line']} letter {r['pos']} ({r['ink']})"
        return f'<img src="{html.escape(r["image"])}" alt="" title="{html.escape(title)}" loading="lazy">'

    n_samples = len(rows)
    n_grouped = sum(len(m) for m in grouping.groups.values())
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Letter groups</title>", f"<style>{_CSS}</style></head><body>",
        "<h1>Letter groups</h1>",
        f"<p class='sub'>{n_samples} samples: {n_grouped} in {len(grouping.groups)} groups, "
        f"{len(grouping.unsure)} unsure. Samples nearest to the group's centre come first; "
        f"hover a sample to see where it is.</p>",
    ]
    for gid, members in grouping.groups.items():
        order = sorted(members, key=lambda m: grouping.distance[m])
        shown = order[:cfg.group_max_shown]
        red = sum(rows[m]["ink"] == "red" for m in members)
        kind = rows[members[0]]["kind"]
        meta = f"{len(members)} samples &middot; {red} red, {len(members) - red} black"
        if kind != "letter":
            meta += f" &middot; {kind}"
        more = f"<span class='more'>+{len(members) - len(shown)} more</span>" if len(members) > len(shown) else ""
        parts.append(f"<div class='group' id='{gid}'><div class='head'><span class='id'>{gid}</span>"
                     f"<span class='meta'>{meta}</span></div>"
                     f"<div class='strip'>{''.join(thumb(m) for m in shown)}{more}</div></div>")
    parts.append(f"<h2 id='unsure'>Unsure ({len(grouping.unsure)})</h2>")
    parts.append(f"<div class='group'><div class='strip'>{''.join(thumb(m) for m in grouping.unsure)}</div></div>")
    parts.append("</body></html>")
    path = out_dir / "groups.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
