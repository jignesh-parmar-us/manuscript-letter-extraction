"""Command line interface:  letter-extractor --input IN --output OUT [--config cfg.json] [--debug]"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from . import __version__, report
from .config import load_config
from .io_utils import FolderError
from .pipeline import process_folder
from .report import PageResult


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="letter-extractor",
        description="Cut every letter out of scanned Devanagari manuscript pages. "
                    "The input folder is only read, never changed.")
    p.add_argument("--input", "-i", required=True, type=Path, help="folder with the manuscript images")
    p.add_argument("--output", "-o", required=True, type=Path, help="folder for the results (created if missing)")
    p.add_argument("--config", "-c", type=Path, help="JSON file that overrides settings in config.py")
    p.add_argument("--workers", "-w", type=int, help="parallel worker processes (default: automatic)")
    p.add_argument("--debug", action="store_true", help="also save overlays of every step to <output>/debug")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.workers is not None:
        overrides["workers"] = args.workers
    if args.debug:
        overrides["debug"] = True
    try:
        cfg = load_config(args.config, **overrides)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    def progress(done: int, total: int, r: PageResult) -> None:
        extra = f" - {r.message}" if r.message else ""
        print(f"[{done}/{total}] {r.file}: {r.status} ({r.seconds:.1f}s){extra}", flush=True)

    summary: dict = {}
    try:
        results = process_folder(args.input, args.output, cfg, progress, summary=summary)
    except FolderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    ok = sum(r.status == report.STATUS_OK for r in results)
    print(f"\nDone: {ok}/{len(results)} pages OK. Report: {args.output / 'report.csv'}")
    print(f"Letters: {summary.get('samples', 0)} samples in {summary.get('groups', 0)} groups, "
          f"{summary.get('unsure', 0)} unsure. Groups: {args.output / 'groups.html'}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
