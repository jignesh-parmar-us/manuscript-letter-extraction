"""Read one line image with Tesseract and print its aksharas (C10):

    python -m letter_extractor.ocr LINE.png [--langs script/Devanagari] [--psm 7] [--height 0]
                                            [--tesseract PATH] [--hocr OUT.hocr]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .aksharas import line_aksharas
from .tesseract import TesseractError, find_tesseract, load_rgb, read_line


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m letter_extractor.ocr",
                                description="Read one line image with Tesseract and print its aksharas.")
    p.add_argument("image", type=Path, help="line image (for example lines/page1_L01.png)")
    p.add_argument("--langs", default="script/Devanagari", help="Tesseract language models, joined by +")
    p.add_argument("--psm", type=int, default=7, help="Tesseract page segmentation mode (7 = one line)")
    p.add_argument("--height", type=int, default=0, help="letter height Tesseract gets, px (0 = as is)")
    p.add_argument("--tesseract", default="", help="path of the tesseract program (default: search)")
    p.add_argument("--hocr", type=Path, help="also save Tesseract's hOCR output to this file")
    args = p.parse_args(argv)
    try:
        engine = find_tesseract(args.tesseract)
        reading = read_line(load_rgb(args.image), engine, langs=args.langs, psm=args.psm,
                            target_height=args.height)
    except (TesseractError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if args.hocr:
        args.hocr.write_text(reading.hocr, encoding="utf-8")
    print(f"Tesseract {engine.version}, {args.langs}, scale {reading.scale:.2f}")
    print(reading.text)
    for a in line_aksharas(reading.words):
        x, y, w, h = a.box
        flag = "  orphan" if a.orphan else ""
        print(f"{a.text}\t{x},{y},{w},{h}\t{a.conf:.0f}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
