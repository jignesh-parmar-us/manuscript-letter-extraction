"""Building the font (F5): the glyphs, outlines and places become one TrueType file, `builds/<name>-<n>.ttf`.

What goes in (font-maker/docs/FONT_PLAN.md, section 4):
  - **Devanagari only** (decision 5): every glyph is reached from its Devanagari label.
  - A group with a one-character label (क, अ, १, ।) is the **base glyph** of that character. A group with a
    longer label (का, कि, क्ष, स्त्री) is an **akshara glyph**: a ligature rule in the `pres` feature swaps the
    typed characters for it (scripts `dev2` and `deva`).
  - **Short i (ि):** text engines move it in front of the consonant before the rules run. HarfBuzz (Chrome)
    puts it right before the last consonant when the ones before it form no half forms (क्ति: `क ् ि त`);
    others may put it in front of the whole cluster (`ि क ् त`). Every akshara with ि therefore gets a rule
    for both orders (for कि they are the same). No half, reph or below forms are built, so every other akshara
    keeps the order it is typed in.
  - Two groups with the same label: the one with more copies is used; the others are listed.
  - **Missing characters** (CHARSET without a base glyph): a box, so the gap shows. Each can be **filled**
    from Noto Serif Devanagari (data/, SIL Open Font License), scaled to this font's headline height and
    marked with a line under it (`mark_filled`, on by default), so a filled letter shows as filled in Word too.
  - **Generated** signs (F9, gen.py): a vowel sign, mark or the virama cut from the book's own aksharas.
    Signs right of the consonant (ा ी ो ौ ॉ ः) get their own width, ि is drawn before the consonant, and marks
    (ं ँ े ै ु ू ृ ् ़) have no width: they sit over or under the end of the glyph before them. They are
    attached to it by GPOS (`abvm` / `blwm`, mark-to-base, the GDEF mark class), with anchors at the base's
    right edge, so every text engine places them the same way (without GPOS, HarfBuzz would place marks by
    its own guess). A generated sign wins over a filled one.
  - Every build gets a new version (1.<n>), so macOS and Word do not keep showing an older build.

Units: UPM font units per em; one em is the book's median line height (F3), the same scale for every glyph.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from .trace import draw

UPM = 1000
SCALE = 4                     # glyph images are 4 times the page size (glyphs.SCALE)
NOTO = Path(__file__).resolve().parent / "data" / "NotoSerifDevanagari-Regular-subset.ttf"
SHORT_I = "ि"


def _chars(*ranges: Tuple[int, int]) -> List[str]:
    return [chr(c) for a, b in ranges for c in range(a, b + 1)]


# The Devanagari characters a normal text needs: what is not covered is listed as missing. Rare letters
# (ऌ ऍ ऎ ऒ ऩ ऱ ऴ ॄ ॅ ॆ ॊ ॠ ॰) are left out of the list; a book's group for one still becomes a glyph.
RARE = set("ऌऍऎऒऩऱऴॄॅॆॊॠ॰")
CHARSET = [c for c in _chars((0x0901, 0x0903), (0x0905, 0x0914), (0x0915, 0x0939), (0x093C, 0x094D),
                             (0x0950, 0x0950), (0x0964, 0x096F)) if c not in RARE]
ZERO_WIDTH = ["‌", "‍"]                    # ZWNJ, ZWJ: kept invisible


def glyph_name(ch: str) -> str:
    return f"uni{ord(ch):04X}"


def akshara_name(g: Dict) -> str:
    return f"a{g['book']}_{g['code']}"


CONSONANT = set(_chars((0x0915, 0x0939), (0x0958, 0x095F)))


def rule_orders(label: str) -> List[List[str]]:
    """The orders a text engine may have the characters in when the rules run: ि before the last
    consonant (HarfBuzz) and ि in front of the cluster; one order when there is no ि."""
    chars = list(label)
    if SHORT_I not in chars:
        return [chars]
    chars.remove(SHORT_I)
    last = max((i for i, c in enumerate(chars) if c in CONSONANT), default=0)
    orders = [chars[:last] + [SHORT_I] + chars[last:], [SHORT_I] + chars]
    return [o for k, o in enumerate(orders) if o not in orders[:k]]


def choose(glyphs: List[Dict]) -> Tuple[Dict[str, Dict], List[Dict]]:
    """One glyph per label (not left out): the group with the most copies; the others as duplicates."""
    by_label: Dict[str, Dict] = {}
    duplicates = []
    for g in sorted((g for g in glyphs if not g.get("left_out")), key=lambda g: (-g["count"], g["group"])):
        if g["label_dev"] in by_label:
            duplicates.append({"group": g["group"], "label": g["label_dev"], "used": by_label[g["label_dev"]]["group"]})
        else:
            by_label[g["label_dev"]] = g
    return by_label, duplicates


def coverage(glyphs: List[Dict], filled: List[str], generated: Optional[List[str]] = None) -> Dict:
    """What the font will draw in the book's letters, what is generated (F9) or filled, what is missing
    (no image is opened)."""
    by_label, duplicates = choose(glyphs)
    base = {label for label in by_label if len(label) == 1}
    made = [c for c in (generated or []) if c not in base]
    return {"base": len(base), "aksharas": len(by_label) - len(base),
            "generated": sum(1 for g in by_label.values() if g.get("generated")),
            "estimated": sum(1 for g in by_label.values() if g.get("placed") == "estimated"),
            "left_out": sorted(g["label_dev"] for g in glyphs if g.get("left_out")),
            "duplicates": duplicates,
            "generated_chars": made,
            "filled": [c for c in filled if c not in base and c not in made],
            "missing": [c for c in CHARSET if c not in base and c not in filled and c not in made],
            "labels": sorted(by_label)}


def ps_name(name: str, fallback: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9]", "", name)[:50]
    return (ascii_name or fallback) + "-Regular"


def _box(pen, width: int, height: int) -> None:
    """A hollow box: the outer square clockwise, the hole counter-clockwise (y up)."""
    t = max(20, width // 10)
    for (x0, y0, x1, y1), outer in (((40, 0, width - 40, height), True), ((40 + t, t, width - 40 - t, height - t), False)):
        pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)] if outer else [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()


def _bar(pen, x0: int, x1: int, y0: int, height: int) -> None:
    """The line under a filled glyph (clockwise)."""
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y0 + height))
    pen.lineTo((x1, y0 + height))
    pen.lineTo((x1, y0))
    pen.closePath()


def mark_features(marks: Dict[str, List[str]], order: List[str], advance: Dict[str, Tuple[int, int]]) -> List[str]:
    """F9: GDEF classes and mark-to-base GPOS for the generated marks: every other glyph is a base with
    its anchor at its right edge on the baseline, every mark's anchor at its own origin. A mark is drawn
    from the right edge of the glyph before it, so this places it where it is drawn, the same in every engine."""
    all_marks = [m for k in ("above", "below") for m in marks[k]]
    if not all_marks:
        return []
    bases = [n for n in order if n not in all_marks and n != ".notdef"]
    by_width: Dict[int, List[str]] = {}
    for n in bases:
        by_width.setdefault(advance[n][0], []).append(n)
    fea = []
    for kind, cls in (("above", "@ABOVE"), ("below", "@BELOW")):
        if marks[kind]:
            fea.append(f"markClass [{' '.join(marks[kind])}] <anchor 0 0> {cls};")
    for kind, cls, feature in (("above", "@ABOVE", "abvm"), ("below", "@BELOW", "blwm")):
        if not marks[kind]:
            continue
        fea.append(f"feature {feature} {{")
        fea += [f"    pos base [{' '.join(names)}] <anchor {w} 0> mark {cls};" for w, names in sorted(by_width.items())]
        fea.append(f"}} {feature};")
    fea.append(f"table GDEF {{ GlyphClassDef [{' '.join(bases)}], , [{' '.join(all_marks)}], ; }} GDEF;")
    return fea


def build(name: str, number: int, fallback_name: str, glyphs: List[Dict], metrics: Dict, filled: List[str],
          mark_filled: bool, contours_of: Callable[[Dict], List[Dict]], out: Path,
          progress: Optional[Callable[[int, int], None]] = None, generated: Optional[Dict[str, Dict]] = None) -> Dict:
    """Write the font to `out` and return its report. `generated`: char -> a generated sign (F9: its kind,
    `contours` in page pixels from its image's top-left, `left` / `right` and `y_top` in page pixels)."""
    generated = generated or {}
    by_label, duplicates = choose(glyphs)
    line_px = metrics.get("line_height") or 120.0
    u = UPM / line_px                                            # font units per page pixel
    gap_px = metrics.get("letter_gap") or 0.0
    space = round((metrics.get("word_space") or line_px * 0.3) * u)

    outlines: Dict[str, object] = {}
    advance: Dict[str, Tuple[int, int]] = {}
    bounds: Dict[str, Tuple[float, float]] = {}

    def add(gname: str, pen: TTGlyphPen, width: int) -> None:
        g = pen.glyph()
        outlines[gname] = g
        advance[gname] = (max(0, int(width)), 0)

    # the book's glyphs
    names: Dict[str, str] = {}                                   # label -> glyph name
    items = list(by_label.items())
    for n, (label, g) in enumerate(items, 1):
        gname = glyph_name(label) if len(label) == 1 else akshara_name(g)
        pen = TTGlyphPen(None)
        top = g["top"] if g.get("top") is not None else -g["size"][1] / SCALE
        draw(contours_of(g), Cu2QuPen(pen, max_err=1.0), u, gap_px / 2, top)
        add(gname, pen, round((g["size"][0] / SCALE + gap_px) * u))
        names[label] = gname
        if progress:
            progress(n, len(items))

    # the headline height (top of क), to scale boxes and filled letters to this font
    ka = by_label.get("क")
    head = round(-ka["top"] * u) if ka and ka.get("top") is not None else round(UPM * 0.45)

    noto = TTFont(NOTO)
    noto_cmap, noto_glyphs = noto.getBestCmap(), noto.getGlyphSet()
    noto_head = noto["glyf"][noto_cmap[ord("क")]].yMax or 1
    s = head / noto_head

    # every character the font answers for: CHARSET, the characters of every label, and filled ones
    chars = sorted(set(CHARSET) | {c for label in by_label for c in label} | set(filled) | set(generated))
    filled_done, missing, made = [], [], []
    marks: Dict[str, List[str]] = {"above": [], "below": []}
    for ch in chars:
        gname = glyph_name(ch)
        if gname in outlines:
            continue
        if ch in generated:                                      # F9: cut from the book's own aksharas
            e = generated[ch]
            pen = TTGlyphPen(None)
            w_px = e["size"][0] / SCALE
            if e["kind"] == "right":
                draw(e["contours"], Cu2QuPen(pen, max_err=1.0), u, e["left"], e["y_top"])
                width = round(max(0.0, e["left"] + w_px + gap_px) * u)
            elif e["kind"] == "left":                            # ि: drawn before the consonant, its hook over it
                draw(e["contours"], Cu2QuPen(pen, max_err=1.0), u, 0.0, e["y_top"])
                width = round(max(1.0, w_px - e["right"]) * u)
            else:                                                # a mark: no width, over / under the glyph before
                draw(e["contours"], Cu2QuPen(pen, max_err=1.0), u, e["left"], e["y_top"])
                width = 0
                marks[e["kind"]].append(gname)
            add(gname, pen, width)
            made.append(ch)
        elif ch in filled and ord(ch) in noto_cmap:
            pen = TTGlyphPen(None)
            src = noto_glyphs[noto_cmap[ord(ch)]]
            rec = DecomposingRecordingPen(noto_glyphs)       # some Noto letters are made of other letters
            src.draw(rec)                                    # (आ ई ओ ि ॥ …): copy them as plain outlines
            bp = BoundsPen(noto_glyphs)
            rec.replay(TransformPen(bp, (s, 0, 0, s, 0, 0)))
            rec.replay(TransformPen(Cu2QuPen(pen, max_err=1.0), (s, 0, 0, s, 0, 0)))
            width = round(src.width * s)
            if mark_filled and bp.bounds:
                x0, y0, x1, _ = bp.bounds
                lo, hi = (0, width) if width > 0 else (round(x0), round(x1))
                _bar(pen, lo + 20, max(lo + 40, hi - 20), round(min(y0, 0)) - 70, 30)
            add(gname, pen, width)
            filled_done.append(ch)
        else:
            pen = TTGlyphPen(None)
            _box(pen, round(head * 0.8), head)
            add(gname, pen, round(head * 0.8))
            missing.append(ch)
        names[ch] = gname

    notdef = TTGlyphPen(None)
    _box(notdef, round(head * 0.8), head)
    add(".notdef", notdef, round(head * 0.8))
    add("space", TTGlyphPen(None), space)
    for ch in ZERO_WIDTH:
        add(glyph_name(ch), TTGlyphPen(None), 0)

    order = [".notdef", "space"] + [glyph_name(c) for c in ZERO_WIDTH] + \
        sorted(n for n in outlines if n.startswith("uni") and n not in {glyph_name(c) for c in ZERO_WIDTH}) + \
        sorted(n for n in outlines if not n.startswith("uni") and n not in (".notdef", "space"))
    cmap = {ord(c): names[c] for c in chars if len(c) == 1}
    cmap[0x20] = "space"
    for ch in ZERO_WIDTH:
        cmap[ord(ch)] = glyph_name(ch)

    for gname, g in outlines.items():
        g.recalcBounds(outlines)
        bounds[gname] = (getattr(g, "yMin", 0), getattr(g, "yMax", 0))
    ascent = max(max(b[1] for b in bounds.values()), head) + 20
    descent = min(min(b[0] for b in bounds.values()), 0) - 20

    ps = ps_name(name, fallback_name)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics({n: (advance[n][0], getattr(outlines[n], "xMin", 0)) for n in order})
    fb.setupHorizontalHeader(ascent=int(ascent), descent=int(descent))
    names_table = {"familyName": name, "styleName": "Regular", "fullName": f"{name} Regular", "psName": ps,
                   "version": f"Version 1.{number:03d}", "uniqueFontIdentifier": f"{ps};build {number}"}
    if filled_done:
        names_table["licenseDescription"] = ("Some letters are copied from Noto Serif Devanagari (Copyright 2022 "
                                             "The Noto Project Authors), licensed under the SIL Open Font License 1.1.")
        names_table["licenseInfoURL"] = "https://openfontlicense.org"
    fb.setupNameTable(names_table)
    fb.setupOS2(sTypoAscender=int(ascent), sTypoDescender=int(descent), sTypoLineGap=0,
                usWinAscent=int(ascent), usWinDescent=int(-descent), fsType=0, achVendID="NONE")
    fb.setupPost(keepGlyphNames=True)
    fb.font["head"].fontRevision = 1 + number / 1000

    rules = sorted(((seq, names[label]) for label in by_label if len(label) > 1 for seq in rule_orders(label)),
                   key=lambda r: -len(r[0]))
    fea = ["languagesystem DFLT dflt;", "languagesystem dev2 dflt;", "languagesystem deva dflt;", ""]
    if rules:
        fea += ["feature pres {"]
        fea += [f"    sub {' '.join(names[c] for c in seq)} by {lig};" for seq, lig in rules]
        fea += ["} pres;"]
    fea += mark_features(marks, order, advance)
    if len(fea) > 4:
        addOpenTypeFeaturesFromString(fb.font, "\n".join(fea))
    fb.font["OS/2"].recalcUnicodeRanges(fb.font)
    fb.font["OS/2"].recalcCodePageRanges(fb.font)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    fb.save(str(tmp))
    tmp.replace(out)

    report = coverage(glyphs, filled, list(generated))
    report.update({"build": number, "file": out.name, "family": name, "ps_name": ps, "glyphs": len(order),
                   "rules": len(rules), "filled": filled_done, "missing": missing, "duplicates": duplicates,
                   "generated_chars": made,
                   "units_per_px": round(u, 3), "space": space})
    return report
