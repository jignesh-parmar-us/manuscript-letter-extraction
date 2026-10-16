#!/bin/zsh
# A copy of the library for experiments (never run them on the real one): the database by SQLite's own
# backup (consistent while the app runs), the book's folder and the word lists as APFS clones (cp -c: no extra
# disk space until a file changes; about 30-40 s for book 6's 150,000 files instead of
# minutes). The book's exports/ and headline-backup/ are left out.
# Usage: tools/harness/copy_library.sh <copy folder> [book folder name]
set -e
SRC="$HOME/Documents/Manuscript Letters"
DST="$1"
BOOK="${2:-0006-vachnamrut-printed-1933-training-data}"
[ -n "$DST" ] || { echo "usage: $0 <copy folder> [book folder]"; exit 1; }
[ -d "$SRC/books/$BOOK" ] || { echo "no book folder $SRC/books/$BOOK"; exit 1; }
DST="${DST:A}"
case "$DST" in
  "${SRC:A}"|"${SRC:A}"/*) echo "the copy must not be inside the library itself"; exit 1;;
esac
mkdir -p "$DST/books"
rm -f "$DST/library.db" "$DST/library.db-wal" "$DST/library.db-shm"
sqlite3 "$SRC/library.db" ".backup '$DST/library.db'"
rm -rf "$DST/books/$BOOK" "$DST/dictionaries"          # the copy's own old folders only
mkdir -p "$DST/books/$BOOK"
# one clone per file (about 150,000 letter pictures): the folders in 6 processes at once
cd "$SRC/books/$BOOK"
find . \( -path ./exports -o -path ./headline-backup \) -prune -o -type d -print | while read -r d; do
  mkdir -p "$DST/books/$BOOK/$d"
done
export TO="$DST/books/$BOOK"
find . \( -path ./exports -o -path ./headline-backup \) -prune -o -type d -print0 |
  xargs -0 -P 6 -n 1 sh -c 'find "$1" -maxdepth 1 -type f -exec sh -c '"'"'cp -c "$@" "$TO/$0/"'"'"' "$1" {} +' _
cd - > /dev/null
[ -d "$SRC/dictionaries" ] && cp -cR "$SRC/dictionaries" "$DST/"
echo "copied to $DST"
