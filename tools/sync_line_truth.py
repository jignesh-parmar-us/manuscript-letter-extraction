"""Once: lines checked in Line truth before 2026-10-20 also corrected and reviewed in Whole lines.

Usage: PYTHONPATH=src .venv/bin/python tools/sync_line_truth.py --library <library> [--book 8] [--apply]

Since 2026-10-20 the latest check holds everywhere (app/truth.py, `sync_existing`). Lines checked earlier in
Line truth are not yet corrected and reviewed (✓) in Whole lines. Without --apply this only lists them. Back up
library.db before --apply (sqlite3 "<library>/library.db" ".backup '<backup>/library.db'").
"""
import argparse

from letter_extractor.app.library import Library
from letter_extractor.app.truth import sync_existing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--book", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    lib = Library(a.library)
    try:
        rows = sync_existing(lib, a.book, apply=a.apply)
    finally:
        lib.close()
    for x in rows:
        was = f"correction '{x['edited_dev']}'" if x["edited_dev"] else "no correction"
        print(f"book {x['book']} · {x['page']} · line {x['line']}: {was}, {'✓' if x['reviewed'] else 'not reviewed'}"
              f" -> '{x['truth_dev']}', ✓")
    print(f"{len(rows)} lines {'synced' if a.apply else 'to sync (nothing changed; --apply to change them)'}")


if __name__ == "__main__":
    main()
