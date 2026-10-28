#!/bin/zsh
# Left-overs of heavy jobs (docs/plans/done/SPEED_PLAN.md, S1): shows them, then stops / deletes them only when you say yes.
#  1. worker processes whose run is gone (their parent died: adopted by launchd, process 1);
#  2. runs still going: tests, the harness (Measure runs inside the app: see the lock);
#  3. the heavy-job lock (~/.manuscript-letters-heavy.lock) and who holds it;
#  4. library copies and harness caches in Claude's scratchpads (/private/tmp/claude-<uid>) and ~/harness.
# Usage: tools/cleanup.sh            (asks before each step)
#        tools/cleanup.sh --list     (only shows)
REPO="${0:A:h:h}"
PY="$REPO/.venv/bin/python"
LIST_ONLY=0; [ "$1" = "--list" ] && LIST_ONLY=1

ask() {                                   # ask "question" -> 0 for yes
  [ $LIST_ONLY = 1 ] && return 1
  read -r "reply?$1 [y/N] "
  [[ "$reply" == [yY]* ]]
}

BASE=$("$PY" -c 'import sys; print(sys.base_prefix)')      # a venv's python runs as the framework's Python.app
procs=$(ps -axo pid=,ppid=,etime=,command= | grep -F -e "$PY" -e "$BASE" | grep -v grep)
orphans=$(print -r -- "$procs" | awk '$2 == 1 && /from multiprocessing\./')
runs=$(print -r -- "$procs" | awk '$2 != 1' | grep -E 'unittest|test_parallel|tools/harness' )

echo "== 1. left-over workers (their run is gone)"
if [ -n "$orphans" ]; then
  print -r -- "$orphans"
  ask "stop these $(print -r -- "$orphans" | wc -l | tr -d ' ') process(es)?" &&
    print -r -- "$orphans" | awk '{print $1}' | xargs kill && echo "stopped"
else echo "none"; fi

echo "\n== 2. runs still going (tests, harness)"
if [ -n "$runs" ]; then
  print -r -- "$runs"
  ask "stop these runs (and their workers)?" && print -r -- "$runs" | awk '{print $1}' | while read -r p; do
    pkill -TERM -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; done && echo "stopped"
else echo "none"; fi

echo "\n== 3. heavy-job lock"
LOCK="$HOME/.manuscript-letters-heavy.lock"
if [ -f "$LOCK" ]; then
  cat "$LOCK"; echo
  pid=$(sed -E 's/.*"pid": *([0-9]+).*/\1/' "$LOCK")
  if kill -0 "$pid" 2>/dev/null; then echo "held by a running process ($pid)"
  else ask "its process is gone: remove the lock?" && rm -f "$LOCK" && echo "removed"; fi
else echo "free"; fi

echo "\n== 4. library copies and harness caches"
found=()
for d in /private/tmp/claude-$(id -u)/*/*/scratchpad/*(N/) /private/tmp/claude-$(id -u)/*/*/scratchpad/*/*(N/) \
         "$HOME/harness"/*(N/); do
  if [ -f "$d/library.db" ] || [ -n "$(print -r -- $d/train<->.npz(N) $d/lines<->.pkl(N))" ]; then found+=("$d"); fi
done
if (( ${#found} )); then
  for d in $found; do printf "%8s  %s  %s\n" "$(du -sh "$d" 2>/dev/null | cut -f1)" \
    "$(stat -f '%Sm' -t '%Y-%m-%d' "$d")" "$d"; done
  echo "(sizes count APFS clones in full; a clone takes no disk space until it is changed)"
  for d in $found; do ask "delete $d ?" && rm -rf "$d" && echo "deleted"; done
else echo "none"; fi
exit 0
