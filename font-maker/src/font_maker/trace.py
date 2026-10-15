"""Tracing (F4): a glyph image becomes outlines (curves), the shape a font stores.

  - **potrace** (the pure-Python `potracer`) turns the ink into closed curves made of straight lines and
    cubic Béziers. Holes (ठ, ढ, ०) come out as curves of their own.
  - The glyph images are 4 times the page size (glyphs.SCALE); they are traced at TRACE_SCALE = 2 times.
    On book 6 that took 34 ms a glyph instead of 60 ms, and the outlines covered the image as well (overlap
    0.96 at both sizes; checked by eye on ठ श्री कु ह्म द्ध ष्ट क ढ).
  - **Direction:** a font fills the inside of outer curves and leaves holes empty by the direction each curve
    runs (TrueType: outer curves clockwise, holes counter-clockwise, with y pointing up). Each curve's depth
    (how many others it lies inside) decides which it is, and it is turned round when needed.
  - Coordinates are kept in **page pixels** from the glyph image's top-left corner (y down), so they do not
    depend on the font's size; `draw` turns them into font units (y up, baseline at 0) for F5.

An outline is made only when it is needed (the glyph dialog, or the font build in F5) and saved next to
its image (`<image>.outline.json`): a glyph is traced once until it changes.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import cv2
import numpy as np
import potrace

TRACE_SCALE = 2           # traced at 2x the page size
TURD = 10                 # specks smaller than this many traced pixels are dropped

Contour = Dict            # {"start": [x, y], "segs": [["L", x, y] | ["C", x1, y1, x2, y2, x, y], ...]}


def trace(img: np.ndarray, image_scale: int) -> List[Contour]:
    """The ink of a glyph image (`True` = ink, enlarged `image_scale` times) as closed curves, in page pixels."""
    f = max(1, image_scale // TRACE_SCALE)
    if f > 1:
        small = cv2.resize(img.astype(np.uint8) * 255, (max(1, img.shape[1] // f), max(1, img.shape[0] // f)),
                           interpolation=cv2.INTER_AREA) >= 128
    else:
        small = img.astype(bool)
    path = potrace.Bitmap(~small).trace(turdsize=TURD, alphamax=1.0, opticurve=True, opttolerance=0.2)
    k = f / image_scale                                     # traced pixels -> page pixels
    contours = []
    for c in path.curves:
        segs = []
        for s in c.segments:
            if s.is_corner:
                segs += [["L", s.c.x * k, s.c.y * k], ["L", s.end_point.x * k, s.end_point.y * k]]
            else:
                segs.append(["C", s.c1.x * k, s.c1.y * k, s.c2.x * k, s.c2.y * k, s.end_point.x * k, s.end_point.y * k])
        contours.append({"start": [c.start_point.x * k, c.start_point.y * k], "segs": segs})
    return orient(contours)


def _points(c: Contour) -> np.ndarray:
    """The curve as a polygon (Béziers sampled), for areas and containment."""
    pts = [np.array(c["start"], float)]
    for s in c["segs"]:
        if s[0] == "L":
            pts.append(np.array(s[1:3], float))
        else:
            p0, c1, c2, p3 = pts[-1], np.array(s[1:3]), np.array(s[3:5]), np.array(s[5:7])
            for t in (0.25, 0.5, 0.75, 1.0):
                pts.append((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t * t * c2 + t ** 3 * p3)
    return np.array(pts)


def _area(pts: np.ndarray) -> float:
    """Signed area with y pointing down."""
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def reverse(c: Contour) -> Contour:
    pts = [c["start"]] + [s[-2:] for s in c["segs"]]       # p0 .. pn (pn = p0: the curve is closed)
    segs = []
    for i in range(len(c["segs"]), 0, -1):
        s, back = c["segs"][i - 1], list(pts[i - 1])
        segs.append(["L", *back] if s[0] == "L" else ["C", s[3], s[4], s[1], s[2], *back])
    return {"start": list(pts[-1]), "segs": segs}


def orient(contours: List[Contour]) -> List[Contour]:
    """Outer curves one way round, holes the other (TrueType, once y points up: outer clockwise)."""
    polys = [_points(c).astype(np.float32) for c in contours]
    out = []
    for i, c in enumerate(contours):
        x, y = (float(v) for v in polys[i][0])
        depth = sum(1 for j, p in enumerate(polys) if j != i and len(p) > 2 and cv2.pointPolygonTest(p, (x, y), False) > 0)
        outer = depth % 2 == 0
        # with y down, an area > 0 runs clockwise on screen; turned upright (y up) that is counter-clockwise,
        # so an outer curve must have area > 0 here to run clockwise in the font
        out.append(c if (_area(polys[i]) > 0) == outer else reverse(c))
    return out


def draw(contours: Sequence[Contour], pen, units_per_px: float, left_px: float, top_px: float) -> None:
    """Draw into a fontTools pen, in font units: x from `left_px`, the image's top `top_px` above (-) or
    below (+) the baseline (F3's `top`), y up."""
    def p(x, y):
        return (round((x + left_px) * units_per_px), round(-(top_px + y) * units_per_px))

    for c in contours:
        pen.moveTo(p(*c["start"]))
        for s in c["segs"]:
            if s[0] == "L":
                pen.lineTo(p(s[1], s[2]))
            else:
                pen.curveTo(p(s[1], s[2]), p(s[3], s[4]), p(s[5], s[6]))
        pen.closePath()


def svg_path(contours: Sequence[Contour]) -> str:
    """The outline as an SVG path (page pixels, y down), to show it next to the image."""
    parts = []
    for c in contours:
        parts.append("M%.1f %.1f" % tuple(c["start"]))
        for s in c["segs"]:
            parts.append(("L%.1f %.1f" % tuple(s[1:3])) if s[0] == "L" else ("C" + " ".join("%.1f" % v for v in s[1:7])))
        parts.append("Z")
    return "".join(parts)
