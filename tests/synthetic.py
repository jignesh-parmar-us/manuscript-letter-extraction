"""Synthetic manuscript pages for the tests: beige paper with a tone gradient, scanner background,
ruled border (red lines and a yellow band), red and black 'text' lines, and margin folio numbers."""
import cv2
import numpy as np

PAPER = (205, 170, 150)
YELLOW = (238, 190, 70)
RED_RULE = (225, 110, 100)
RED_INK = (215, 75, 65)
BLACK_INK = (35, 30, 35)

W, H = 1400, 700
SCANNER = 20                          # scanner background around the page
BLOCK = (230, 110, 1170, 590)         # x0, y0, x1, y1 of the text
FOLIO = (60, 140, 130, 180)           # folio number in the left margin
LINE_PITCH = 60
RED_LINES = 4                         # first lines are red, the rest black


def _border(img, x0, mirror=False):
    parts = [(0, 3, RED_RULE), (10, 34, YELLOW), (41, 44, RED_RULE)]
    if mirror:
        parts = [(44 - b, 44 - a, c) for a, b, c in parts]
    for a, b, c in parts:
        img[SCANNER + 10:H - SCANNER - 10, x0 + a:x0 + b] = c


def make_page(seed=0):
    """Return (rgb, truth) where truth maps 'red' / 'black' to the bool mask of the drawn text."""
    rng = np.random.default_rng(seed)
    img = np.empty((H, W, 3), np.float32)
    img[:] = PAPER
    img += np.linspace(-10, 10, W)[None, :, None]           # uneven paper tone
    img += rng.normal(0, 3.0, (H, W, 1))                     # paper grain
    _border(img, 150)
    _border(img, W - 150 - 44, mirror=True)
    truth = {"red": np.zeros((H, W), np.uint8), "black": np.zeros((H, W), np.uint8)}
    x0, y0, x1, y1 = BLOCK
    for i, y in enumerate(range(y0 + 20, y1, LINE_PITCH)):
        colour, key = (RED_INK, "red") if i < RED_LINES else (BLACK_INK, "black")
        for x in range(x0, x1 - 40, 48):                     # one 'letter': headline piece + stem + bowl
            for canvas, value in ((img, colour), (truth[key], 1)):
                cv2.line(canvas, (x, y), (x + 38, y), value, 5)
                cv2.line(canvas, (x + 30, y), (x + 30, y + 34), value, 5)
                cv2.ellipse(canvas, (x + 15, y + 22), (10, 9), 0, 0, 360, value, 4)
    fx0, fy0, fx1, fy1 = FOLIO
    folio = np.zeros((H, W), np.uint8)                       # putText draws on 8-bit images only
    cv2.putText(folio, "12", (fx0, fy1), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 1, 3)
    img[folio > 0] = BLACK_INK
    img = cv2.GaussianBlur(img, (0, 0), 0.7)                 # scanner softness
    img[:SCANNER] = img[-SCANNER:] = (25, 20, 25)            # scanner background
    img[:, :SCANNER] = img[:, -SCANNER:] = (25, 20, 25)
    rgb = np.clip(img, 0, 255).astype(np.uint8)
    return rgb, {k: v.astype(bool) for k, v in truth.items()}


def make_lines_page(n_lines=6, pitch=90, slope=0.012, wave=4.0, seed=1):
    """Black text lines whose headlines slope and wave: y(x) = y0 + slope * x + wave * sin(x / 160).

    Every letter has a headline piece, a stem and a bowl. Every third letter also has a detached
    dot above the headline (like anusvara) and every fifth a detached tick below the main zone (like
    a loose lower matra). Returns (rgb, headlines, marks): headlines[i] is the true headline row for
    every column, marks is a list of (line_number, x, y) of the detached marks."""
    rng = np.random.default_rng(seed)
    w, h = 1300, 120 + n_lines * pitch
    img = np.empty((h, w, 3), np.float32)
    img[:] = PAPER
    img += np.linspace(-8, 8, h)[:, None, None]
    img += rng.normal(0, 3.0, (h, w, 1))
    xs = np.arange(w)
    heads, marks = [], []
    for i in range(n_lines):
        y0 = 70 + i * pitch
        hy = y0 + slope * xs + wave * np.sin(xs / 160.0)
        heads.append(hy)
        for k, x in enumerate(range(80, w - 100, 48)):
            y = lambda dx: int(round(hy[min(w - 1, x + dx)]))      # noqa: E731
            pts = np.array([[x + dx, y(dx)] for dx in range(0, 39, 2)], np.int32)
            cv2.polylines(img, [pts], False, BLACK_INK, 5)
            cv2.line(img, (x + 30, y(30)), (x + 30, y(30) + 34), BLACK_INK, 5)
            cv2.ellipse(img, (x + 15, y(15) + 22), (10, 9), 0, 0, 360, BLACK_INK, 4)
            if k % 3 == 0:
                cv2.circle(img, (x + 15, y(15) - 14), 4, BLACK_INK, -1)
                marks.append((i + 1, x + 15, y(15) - 14))
            if k % 5 == 0:
                cv2.line(img, (x + 22, y(22) + 46), (x + 30, y(22) + 50), BLACK_INK, 4)
                marks.append((i + 1, x + 26, y(22) + 48))
    img = cv2.GaussianBlur(img, (0, 0), 0.7)
    return np.clip(img, 0, 255).astype(np.uint8), heads, marks
