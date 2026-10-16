# Working rules for this repo

Manuscript letter extraction: cut, group, label and read printed and handwritten Gujarati /
Devanagari books. Python backend (`src/letter_extractor`, FastAPI app in `app/`), React screen
in `frontend/`, SQLite library at `~/Documents/Manuscript Letters`.

## Running and testing
- Build the screen: `npm run build` (again after changes in `frontend/`)
- App in the browser on a fixed port: `PYTHONPATH=src .venv/bin/python -m letter_extractor.app --browser --port 8675`
- Command-line pipeline: `PYTHONPATH=src .venv/bin/python -m letter_extractor --input samples --output out --debug`
- Backend tests in 4 processes: `PYTHONPATH=src .venv/bin/python tools/test_parallel.py fast` (all but the
  sample-page and end-to-end tests) or `... tools/test_parallel.py full` (all; takes the heavy-job lock).
  One module: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_wholelines`. The old one-process run
  `python -m unittest discover -s tests` still works (about 6 min).
- Left-over test / harness processes, library copies and caches: `tools/cleanup.sh` (asks before it stops or deletes)
- Screen tests and type check: `npm test`, `npm run typecheck`
- The Mac is Intel. Give macOS commands for zsh (`set VAR=x` is Windows syntax).
- **Font Maker** is a separate app in `font-maker/` (own code, screen, tests; reads the library read-only).
  Its commands, plan and rules are in `font-maker/README.md` and `font-maker/docs/FONT_PLAN.md`. Keep its
  tests few and light; font-maker-only changes never need the main suites.

## Commits
- One commit per task or fix. Commit only when I say "commit" (or "implement + commit").
- Before a commit, run the tests for the code you changed
  (e.g. `PYTHONPATH=src .venv/bin/python -m unittest tests.test_wholelines`), and `npm test`
  only if `frontend/` changed. Run the full suites at the end of a chunk or before a merge
  (backend `full` ≈ 2 min, `fast` ≈ 2 min, screen ≈ 1.5 min). Add a test with every fix.
- **No heavy runs while implementing:** no Measure, no harness, no full backend suite. Run only the
  tests of the changed modules; prove "same numbers" changes with small equality tests. Heavy runs only
  when I ask, one at a time (`docs/SPEED_PLAN.md`).

## Plans and docs
- When the implementation differs from the plan, update the plan in the same commit:
  `docs/IMPLEMENTATION_PLAN.md` (Phase 1, C0–C9), `docs/implementation_plan_phase2.md` (C10+),
  `docs/implementation_plan_phase3_lean.md` (C19+, what is built; the full `implementation_plan_phase3.md`
  is the reference for what was left for later), `docs/SPEED_PLAN.md` (S1–S4),
  `docs/SEGMENTATION_PLAN.md` (line search). Record what changed and why. Also update the chunks
  that come after it: status, files, settings.
- Tuning numbers go in `docs/TUNING.md` / `docs/TUNING_PHASE2.md`.
- When the UI changes, update the help pages in `docs/help/` and the README.

## Fairness rule (groups, reader, training)
- Never weight letters by group size or how often they occur. A group with a single reviewed
  sample must be usable for training and reading.
- Balance the copies per group: cap large groups at their best copies, top up small groups with
  duplicates or variants. The minimum number of samples per group is a setting, never hardcoded.
- How often letters occur belongs only in the language model.

## Measuring reading quality
- Judge every reading change only on my hand-checked lines (Read Book → Line truth, table
  `line_truth`), fold-fair: leave out the tested pages' letters and corrections.
- Show before/after numbers and a line-by-line page I can check by eye. Don't quote accuracy
  measured on training letters.
- Every change must work for both printed and handwritten books. Say so if it affects only one.

## Data safety
- Never delete, rebuild or bulk-change my reviewed groups, labels or line truth without asking.
- Back up the library before any bulk backend change, and tell me where the backup is.
- For experiments, use a copy of the library in the scratchpad, not the real one.

## How I phrase requests
- "Brainstorm only" / "don't implement": answer and recommend, change no code.
- "Plan, then wait": write the plan and stop for my answers.
- If a request is ambiguous or touches reviewed data, ask before acting.
