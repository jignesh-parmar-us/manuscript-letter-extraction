"""C30a: the likely wrong checked texts, from a scoring run (no reading, no library: light).

Usage: PYTHONPATH=src .venv/bin/python tools/tesstrain/suspects.py --data <dir> [--name score] [--reader tuned]

Reads <dir>/<name>.json (score.py) and writes <dir>/<name>-suspects.html: every place where the fold's model reads a
line differently from its checked text, the model's most confident first, with the line's picture from the export
(<dir>/all/). Fix the real mistakes in the app (Read Book → Line truth), then export and train again.
"""
import argparse
import json
from pathlib import Path

from letter_extractor.app.tesstrain import suspects, suspects_page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--name", default="score")
    ap.add_argument("--reader", default="tuned", help="which reading to compare (default the fold's model, no LM)")
    a = ap.parse_args()
    data = Path(a.data)
    result = json.loads((data / f"{a.name}.json").read_text(encoding="utf-8"))
    found = suspects(result, a.reader)
    page = data / f"{a.name}-suspects.html"
    page.write_text(suspects_page(found, f"Likely wrong checked texts: book {result['book']}"), encoding="utf-8")
    print(f"{len(found)} places on {len({(s['page'], s['line']) for s in found})} lines")
    print(page)


if __name__ == "__main__":
    main()
