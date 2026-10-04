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


JOINS = ["gap", "thin", "tiny_gap", "touch"]   # cycled between neighbouring letters


def make_break_page(n_lines=3, letters=12, pitch=110, colour=BLACK_INK):
    """Lines of block letters whose headline joins are known: 'gap' (8 px without ink), 'thin'
    (the headline narrows to a 1 px neck), 'tiny_gap' (1 px, below min_break_px: no break) and
    'touch' (continuous headline: no break). Every line ends with a headless danda.

    Returns (rgb, expected) where expected[i] = (break_x_ranges, joined_x) for line i+1: every
    range in break_x_ranges must hold a cut, no cut may fall within 6 px of a joined_x."""
    rng = np.random.default_rng(3)
    lw, gap = 46, {"gap": 8, "thin": 4, "tiny_gap": 1, "touch": 0}
    # wide enough that joined headlines are far shorter than a ruled line (15% of the width)
    width = max(1600, 80 + letters * (lw + 8) + 120)
    # tall enough that a stem plus headline is far shorter than a ruled line (15% of the height)
    h = max(800, 60 + n_lines * pitch)
    img = np.empty((h, width, 3), np.float32)
    img[:] = PAPER
    img += rng.normal(0, 3.0, (h, width, 1))
    expected = []
    for i in range(n_lines):
        hy = 60 + i * pitch
        x = 80
        breaks, joined = [], []
        for k in range(letters):
            cv2.rectangle(img, (x, hy - 5), (x + lw - 1, hy + 5), colour, -1)           # headline
            cv2.rectangle(img, (x + lw - 12, hy + 5), (x + lw - 5, hy + 52), colour, -1)  # stem
            cv2.ellipse(img, (x + 16, hy + 28), (11, 12), 0, 0, 360, colour, 5)          # bowl
            if k == letters - 1:
                x += lw
                break
            join = JOINS[k % len(JOINS)]
            g = gap[join]
            if join == "thin":                                 # 1 px neck through the join
                cv2.rectangle(img, (x + lw, hy), (x + lw + g - 1, hy), colour, -1)
            if join in ("gap", "thin"):
                breaks.append((x + lw - 1, x + lw + g + 1))
            else:
                joined.append(x + lw + g // 2)
            x += lw + g
        dx = x + 30                                             # headless danda
        cv2.rectangle(img, (dx, hy - 2), (dx + 7, hy + 52), colour, -1)
        breaks.append((x, dx))
        expected.append((breaks, joined))
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    return np.clip(img, 0, 255).astype(np.uint8), expected


def _block_letter(img, x, hy, colour, lw=46):
    """Headline, stem on the right, bowl on the left: a letter body with a gap before its stem."""
    cv2.rectangle(img, (x, hy - 5), (x + lw - 1, hy + 5), colour, -1)
    cv2.rectangle(img, (x + lw - 12, hy + 5), (x + lw - 5, hy + 52), colour, -1)
    cv2.ellipse(img, (x + 16, hy + 28), (11, 12), 0, 0, 360, colour, 5)


def make_letters_page(n_lines=3, pitch=110, colour=BLACK_INK):
    """Lines that exercise every join / split rule, left to right:

    1 plain letter | 2 letter + aa bar (thin headline join) | 3 short-i hook + letter (curl over it)
    | 4, 5 two letters whose headlines touch (bodies apart) | 6 letter + detached anusvara dot and an
    e-mark that touches its headline but leans mostly over letter 5
    | 7 double danda | 8 letter + detached lower tick | 9 letter + visarga (two dots that nearly
    touch, so they look like a tall stroke apart from the waist between them).

    Returns (rgb, expected): expected[i] lists, per letter of line i+1, (kind, x_from, x_to,
    must_contain) where the letter's box must span at least x_from..x_to and contain the points
    in must_contain (x, y)."""
    rng = np.random.default_rng(5)
    w, h = 1600, max(800, 60 + n_lines * pitch)
    img = np.empty((h, w, 3), np.float32)
    img[:] = PAPER
    img += rng.normal(0, 3.0, (h, w, 1))
    expected = []
    for i in range(n_lines):
        hy, exp = 80 + i * pitch, []
        x = 80
        _block_letter(img, x, hy, colour)                                       # 1
        exp.append(("letter", x, x + 45, []))
        x += 54
        _block_letter(img, x, hy, colour)                                       # 2: letter + aa bar
        cv2.rectangle(img, (x + 46, hy), (x + 49, hy), colour, -1)             # 1 px neck
        cv2.rectangle(img, (x + 50, hy - 5), (x + 63, hy + 5), colour, -1)     # bar's own headline
        cv2.rectangle(img, (x + 56, hy + 5), (x + 63, hy + 52), colour, -1)    # bar
        exp.append(("letter", x, x + 63, [(x + 60, hy + 40)]))
        x += 64 + 12
        hook = x                                                                # 3: short-i hook
        cv2.rectangle(img, (x, hy - 5), (x + 13, hy + 5), colour, -1)
        cv2.rectangle(img, (x + 3, hy + 5), (x + 10, hy + 52), colour, -1)
        cv2.ellipse(img, (x + 30, hy - 8), (22, 14), 0, 180, 360, colour, 5)   # curl, ends over the letter
        x += 20
        _block_letter(img, x, hy, colour)
        exp.append(("letter", hook, x + 45, [(hook + 6, hy + 40), (hook + 30, hy - 21)]))
        x += 54
        _block_letter(img, x, hy, colour)                                       # 4, 5: touching
        cv2.rectangle(img, (x + 46, hy - 5), (x + 50, hy + 5), colour, -1)
        exp.append(("letter", x + 5, x + 40, []))
        _block_letter(img, x + 51, hy, colour)
        exp.append(("letter", x + 56, x + 96, []))
        x += 51 + 54
        _block_letter(img, x, hy, colour)                                       # 6: anusvara + e-mark
        cv2.circle(img, (x + 30, hy - 17), 5, colour, -1)
        cv2.line(img, (x + 8, hy - 5), (x - 30, hy - 26), colour, 4)            # leans over letter 5
        exp.append(("letter", x - 25, x + 45, [(x + 30, hy - 17), (x - 25, hy - 23)]))
        x += 70
        for k in (0, 14):                                                       # 7: double danda
            cv2.rectangle(img, (x + k, hy - 3), (x + k + 7, hy + 52), colour, -1)
        exp.append(("danda", x, x + 21, []))
        x += 45
        _block_letter(img, x, hy, colour)                                       # 8: lower tick
        cv2.line(img, (x + 34, hy + 62), (x + 44, hy + 68), colour, 4)
        exp.append(("letter", x, x + 45, [(x + 39, hy + 65)]))
        x += 60
        _block_letter(img, x, hy, colour)                                       # 9: visarga
        v = x + 46 + 14                                                          # two dots that touch
        cv2.ellipse(img, (v, hy + 12), (7, 12), 0, 0, 360, colour, -1)
        cv2.ellipse(img, (v, hy + 37), (7, 12), 0, 0, 360, colour, -1)
        exp.append(("letter", x, v + 6, [(v, hy + 12), (v, hy + 37)]))
        expected.append(exp)
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    return np.clip(img, 0, 255).astype(np.uint8), expected
