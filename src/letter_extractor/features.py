"""Shape fingerprints of letter samples (C4, Section 8.2 of the requirements).

A fingerprint is computed from the letter's ink mask only, so paper tone, ink colour (red or
black) and neighbouring ink do not matter:

1. crop to the ink, pad to a square (keeping the aspect ratio), resize to `normalize_size`;
2. blur slightly, so a stroke shifted by a pixel or two still matches;
3. two parts, each scaled to unit length: the blurred image at `fp_pixels` x `fp_pixels` (where the
   ink is) and a HOG descriptor (which way the strokes run);
4. the letter's width and height relative to the line spacing, so a dot and a large letter of
   similar shape stay apart.

The whole vector has unit length, so the Euclidean distance between two fingerprints is between 0
(same shape) and 2.
"""
from __future__ import annotations

import cv2
import numpy as np

from .config import Config

HOG_CELLS = 6                          # the image is divided into 6 x 6 cells (8 px at 48 px)...
HOG_BINS = 9                           # ...each with a 9-bin histogram of stroke directions (0-180 degrees)


def hog(img: np.ndarray) -> np.ndarray:
    """Histogram of oriented gradients: per cell, gradient strength by direction; cells normalized
    in overlapping 2 x 2 blocks (L2, clipped at 0.2, renormalized). Written out here because
    OpenCV 5 no longer ships cv2.HOGDescriptor in the main package. 6 x 6 cells (rather than 4 x 4)
    and a 24 px image part separate look-alikes such as vaa / naa and chhe / che much better."""
    g = img.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    ang = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    b = np.minimum((ang / (180.0 / HOG_BINS)).astype(np.int64), HOG_BINS - 1)
    size = img.shape[0]
    cell = size // HOG_CELLS
    rows = np.minimum(np.arange(size) // cell, HOG_CELLS - 1)
    cy, cx = np.meshgrid(rows, rows, indexing="ij")
    hist = np.zeros((HOG_CELLS, HOG_CELLS, HOG_BINS), np.float32)
    np.add.at(hist, (cy.ravel(), cx.ravel(), b.ravel()), mag.ravel())
    blocks = []
    for i in range(HOG_CELLS - 1):
        for j in range(HOG_CELLS - 1):
            v = hist[i:i + 2, j:j + 2].ravel()
            v = v / (np.linalg.norm(v) + 1e-6)
            v = np.minimum(v, 0.2)
            blocks.append(v / (np.linalg.norm(v) + 1e-6))
    return np.concatenate(blocks)


def normalize(mask: np.ndarray, size: int) -> np.ndarray:
    """Ink mask -> square uint8 image (ink 255 on 0), ink centred, aspect ratio kept."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return np.zeros((size, size), np.uint8)
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    side = max(h, w) + 2
    sq = np.zeros((side, side), np.uint8)
    y0, x0 = (side - h) // 2, (side - w) // 2
    sq[y0:y0 + h, x0:x0 + w] = m.astype(np.uint8) * 255
    return cv2.resize(sq, (size, size), interpolation=cv2.INTER_AREA)


def fingerprint(mask: np.ndarray, spacing: float, cfg: Config) -> np.ndarray:
    size = cfg.normalize_size
    img = normalize(mask, size)
    img = cv2.GaussianBlur(img, (0, 0), cfg.fp_blur)
    pix = cv2.resize(img, (cfg.fp_pixels, cfg.fp_pixels), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    hog_v = hog(img)
    parts = []
    for v, weight in ((pix, cfg.fp_pixel_weight), (hog_v, cfg.fp_hog_weight)):
        n = float(np.linalg.norm(v))
        parts.append(weight * v / n if n > 0 else v)
    ys, xs = np.nonzero(mask)
    h = (ys.max() - ys.min() + 1) if ys.size else 0   # size of the ink, not of the mask array
    w = (xs.max() - xs.min() + 1) if xs.size else 0
    parts.append(cfg.fp_size_weight * np.array([w / spacing, h / spacing], np.float32))
    v = np.concatenate(parts)
    return (v / max(float(np.linalg.norm(v)), 1e-9)).astype(np.float32)


def fingerprint_size(cfg: Config) -> int:
    return cfg.fp_pixels ** 2 + (HOG_CELLS - 1) ** 2 * 4 * HOG_BINS + 2
