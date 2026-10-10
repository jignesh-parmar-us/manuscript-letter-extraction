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

from ..features import hog, normalize

SIZE = 40
PIXELS = 20


def features(mask: np.ndarray, spacing: float) -> np.ndarray:
    """One letter's feature vector (float32). `spacing`: its page's line spacing in pixels."""
    img = normalize(mask, SIZE)
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    pix = cv2.resize(img, (PIXELS, PIXELS), interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255.0
    h_vec = hog(img)
    ys, xs = np.nonzero(mask)
    h = float(ys.max() - ys.min() + 1) if ys.size else 0.0
    w = float(xs.max() - xs.min() + 1) if xs.size else 0.0
    sp = max(spacing, 1.0)
    size = np.array([w / max(h, 1.0), w / sp, h / sp], np.float32)
    return np.concatenate([pix, h_vec.astype(np.float32), size]).astype(np.float32)


def dimension() -> int:
    return len(features(np.ones((10, 10), bool), 100.0))


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
