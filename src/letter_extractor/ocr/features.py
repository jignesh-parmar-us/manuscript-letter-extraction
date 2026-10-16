"""Shape features of a letter for the letter reader (C14).

Finer than the grouping fingerprints (`letter_extractor.features`), and they keep the letter's size,
since the reader must tell a dot from a letter and a letter from two:
1. crop the ink mask, pad it to a square (aspect ratio kept), resize to 40 px, blur slightly;
2. the image at 20 x 20 (where the ink is);
3. stroke directions (HOG, 6 x 6 cells) of the 40 px image;
4. the aspect ratio, and the width and height relative to the line spacing.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..features import HOG_BINS, HOG_CELLS, normalize

SIZE = 40
PIXELS = 20
FEATURE_VERSION = 1          # raise when the features change: the kept rows (app/linestore.py) are then made again


def features(mask: np.ndarray, spacing: float) -> np.ndarray:
    """One letter's feature vector (float32). `spacing`: its page's line spacing in pixels. Computed as
    `features_batch` does, so the same numbers every time (`hog` of one image normalises with NumPy's norm,
    whose last bit depends on where the array lies in memory) and the same as a window's (S3, 2026-10-16)."""
    return features_batch([mask], spacing)[0]


def dimension() -> int:
    return PIXELS * PIXELS + (HOG_CELLS - 1) ** 2 * 4 * HOG_BINS + 3          # picture, stroke directions, size


def varied(mask: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A slightly changed copy of a letter, as the same hand or print varies: a small rotation and
    slant, strokes one pixel thicker or thinner, and sometimes a trimmed edge (a cut a little off)."""
    m = mask.astype(np.uint8) * 255
    h, w = m.shape
    pad = max(4, int(0.15 * max(h, w)))
    m = cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    H, W = m.shape
    angle = rng.uniform(-4, 4)
    shear = rng.uniform(-0.12, 0.12)
    A = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    A[0, 1] += shear
    A[0, 2] -= shear * H / 2
    m = cv2.warpAffine(m, A, (W, H), flags=cv2.INTER_NEAREST, borderValue=0)
    t = rng.integers(-1, 2)
    if t:
        k = np.ones((2, 2), np.uint8)
        m = cv2.dilate(m, k) if t > 0 else cv2.erode(m, k)
    out = m > 127
    if rng.random() < 0.3 and out.any():                     # trim a few columns off one side
        cols = np.flatnonzero(out.any(axis=0))
        cut = max(1, int(0.08 * len(cols)))
        if rng.random() < 0.5:
            out[:, : cols[0] + cut] = False
        else:
            out[:, cols[-1] - cut + 1:] = False
    return out if out.sum() >= 10 else mask


def features_batch(masks, spacing: float, tight: bool = False) -> np.ndarray:
    """`features` of many masks at once (one row each), with the stroke directions (HOG) computed for all of
    them together. `tight`: every mask is cropped to its ink already (the line search's windows), so its ink
    is not searched again: the same numbers."""
    from ..features import hog_batch
    if not len(masks):
        return np.zeros((0, dimension()), np.float32)
    imgs = np.stack([cv2.GaussianBlur(normalize(m, SIZE, tight), (0, 0), 0.8) for m in masks])
    pix = np.stack([cv2.resize(im, (PIXELS, PIXELS), interpolation=cv2.INTER_AREA) for im in imgs]).astype(np.float32)
    pix = pix.reshape(len(masks), -1) / 255.0
    h_vec = hog_batch(imgs).astype(np.float32)
    sp = max(spacing, 1.0)
    size = []
    for m in masks:
        if tight:
            h, w = (float(v) for v in m.shape)
        else:
            ys, xs = np.nonzero(m)
            h = float(ys.max() - ys.min() + 1) if ys.size else 0.0
            w = float(xs.max() - xs.min() + 1) if xs.size else 0.0
        size.append([w / max(h, 1.0), w / sp, h / sp])
    return np.concatenate([pix, h_vec, np.array(size, np.float32)], axis=1).astype(np.float32)
