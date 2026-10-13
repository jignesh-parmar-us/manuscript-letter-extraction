#!/bin/zsh
# A copy of the library for experiments (never run them on the real one): the database by SQLite's own
# backup (consistent while the app runs), the book's folder and the word lists.
# Usage: tools/harness/copy_library.sh <copy folder> [book folder name]
set -e
SRC="$HOME/Documents/Manuscript Letters"
DST="$1"
BOOK="${2:-0006-vachnamrut-printed-1933-training-data}"
[ -n "$DST" ] || { echo "usage: $0 <copy folder> [book folder]"; exit 1; }
mkdir -p "$DST/books"
rm -f "$DST/library.db"
sqlite3 "$SRC/library.db" ".backup '$DST/library.db'"
rsync -a --delete "$SRC/books/$BOOK/" "$DST/books/$BOOK/"
rsync -a "$SRC/dictionaries/" "$DST/dictionaries/"
echo "copied to $DST"
