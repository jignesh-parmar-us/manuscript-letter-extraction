// Label suggestions in the Review tab (C12).
// - SuggestPanel (in the side bar): read the book with Tesseract (a background job) or with the
//   labelled groups of other books (C13; the main reader of handwritten books), accept all
//   suggestions above a share in one undoable step, and see how the suggestions compare with the
//   labels given so far. On printed books, "Fix cuts with Tesseract" splits samples that hold several
//   letters and joins letters cut in pieces (C12b), as one undoable step; "Fix ા bars" gives aa bars
//   cut onto the next letter (નાર as ન + ાર) back to their letter, by shape only (bars.py, barfix.py).
// - SuggestionChip (on a group): accept, change or reject its suggestion; or merge into the group
//   that already has the suggested label.
// - ReadingsLine (on a group): what its samples were read as; select the samples of one reading to
//   split a mixed group.
// A suggestion never labels a group by itself: every accept is a normal, undoable action.
import { useCallback, useEffect, useState } from "react";
import { api, Book, ENGINE_NAME, Group, Job, localTime, ReferenceBook, SuggestionAccuracy, TesseractStatus } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { ReviewContext } from "./Review";

/** Two strong readings: the second most common one is at least 2 samples and a quarter of those read. */
export function isMixed(g: Group): boolean {
  const second = g.readings[1];
  return !!second && second.count >= Math.max(2, 0.25 * g.read);
}

/** Groups "Accept all" would label: a suggestion of at least `minShare`, no merge needed, not locked. */
export function bulkCandidates(groups: Group[], minShare: number): Group[] {
  return groups.filter(
    (g) => g.suggestion && !g.label_dev && !g.locked && !g.suggestion.merge_into && g.suggestion.share >= minShare - 1e-9,
  );
}

/** The reading a sample of this group should have: its suggestion, else its label, else the most common one. */
export function expectedReading(g: Group): string {
  return g.suggestion?.label_dev || g.label_dev || g.readings[0]?.label_dev || "";
}

const pct = (share: number) => `${Math.round(share * 100)}%`;

export function SuggestPanel({ book, ctx, onRead }: { book: Book; ctx: ReviewContext; onRead: () => void }) {
  const [status, setStatus] = useState<TesseractStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [accuracy, setAccuracy] = useState<SuggestionAccuracy[]>([]);
  const [refs, setRefs] = useState<ReferenceBook[] | null>(null);
  const [chosen, setChosen] = useState<Set<number> | null>(null); // null: the default reference books
  const [threshold, setThreshold] = useState(() => Math.round(100 * Number(book.settings.bulk_accept_share ?? 0.9)));
  const [dialog, confirm] = useConfirm();
  const onEnd = useCallback(
    (j: Job) => {
      if (j.status === "done") onRead();
    },
    [onRead],
  );
  const [job, setJob] = useJob(
    book.job?.kind === "suggest" || book.job?.kind === "fix_cuts" || book.job?.kind === "fix_bars" ? book.job : null,
    onEnd,
  );
  const run = book.ocr_runs?.find((r) => r.engine === "tesseract");
  const booksRun = book.ocr_runs?.find((r) => r.engine === "books");
  const printed = book.writing === "printed";

  useEffect(() => {
    api.tesseract(book.id).then(setStatus, setError);
    api.referenceBooks(book.id).then(setRefs, () => setRefs([]));
  }, [book.id]);
  const runTimes = (book.ocr_runs ?? []).map((r) => `${r.engine}@${r.finished_at}`).join(",");
  useEffect(() => {
    const ran = (book.ocr_runs ?? []).map((r) => r.engine);
    if (!ran.length || book.labelled === 0) {
      setAccuracy([]);
      return;
    }
    Promise.all(ran.map((e) => api.accuracy(book.id, e))).then(setAccuracy, () => setAccuracy([]));
  }, [book.id, book.labelled, runTimes, ctx.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const usable = (refs ?? []).filter((r) => r.comparable);
  const picked = chosen ?? new Set(usable.filter((r) => r.default).map((r) => r.id));
  function toggle(id: number) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  }
  async function startBooks() {
    setError(null);
    try {
      setJob(await api.suggestBooks(book.id, [...picked]));
    } catch (e) {
      setError(e);
    }
  }

  async function start() {
    setError(null);
    try {
      setJob(await api.suggest(book.id));
    } catch (e) {
      setError(e);
    }
  }

  async function fixCuts() {
    const ok = await confirm(
      "Split samples that hold several letters, put vowel bars (ा ो ौ) back on their letter, and join letters " +
        "cut in pieces, where Tesseract's reading shows it and the new pieces look like letters of this book? " +
        "Each fixed letter goes into the group with its reading's label (or a new group with that label, " +
        "marked not reviewed); the rest go to Unsure. Undo takes all of it back in one step.",
      "Fix cuts",
    );
    if (!ok) return;
    setError(null);
    try {
      setJob(await api.fixCuts(book.id));
    } catch (e) {
      setError(e);
    }
  }

  async function fixBars() {
    const ok = await confirm(
      "Give ા bars back to their letter where the cutting joined them to the next one (નાર cut as ન + ાર " +
        "becomes ના + ર), and join bars cut off on their own (the stem of ણ) to the letter before? A bar with " +
        "the hook of િ above it (રવિ) is never touched. " +
        "The new letters go into the group their shape matches, the rest to Unsure. Undo takes all of it back in one step.",
      "Fix ા bars",
    );
    if (!ok) return;
    setError(null);
    try {
      setJob(await api.fixBars(book.id));
    } catch (e) {
      setError(e);
    }
  }

  const [splitNote, setSplitNote] = useState("");
  async function splitMixed() {
    setSplitNote("");
    const r = await ctx.act(() => api.splitMixed(book.id));
    if (r) setSplitNote(Number(r.groups) ? `${r.groups} groups split off (${r.samples} letters).` : "No mixed group to split.");
  }

  const candidates = bulkCandidates(ctx.groups, threshold / 100);
  async function acceptAll() {
    const n = candidates.length;
    if (!(await confirm(`Label ${n} group${n === 1 ? "" : "s"} with their suggested labels? Undo takes it back in one step.`, "Label them")))
      return;
    ctx.act(() =>
      api.acceptSuggestions(
        book.id,
        candidates.map((g) => ({ group_id: g.id, label_dev: g.suggestion!.label_dev })),
      ),
    );
  }

  const running = job?.status === "running";
  const anyRun = !!(run || booksRun);
  const lastRun = (r: typeof run, who: string) =>
    r &&
    `${who} read ${localTime(r.finished_at)}: ${String(r.result.samples_matched)} of ${String(r.result.samples)} letters, ` +
      `${String(r.result.groups_with_suggestion)} groups with a suggestion` +
      (Number(r.result.groups_split) > 0 ? `, ${String(r.result.groups_split)} mixed groups split` : "");
  const tesseractButton = (
    <button
      key="tesseract"
      className={printed ? "primary" : ""}
      disabled={running || !status?.ok}
      title={
        status && !status.ok
          ? status.error
          : printed
            ? "Tesseract reads every line; each group gets the label most of its letters were read as"
            : "Tesseract reads print; on handwriting about a third of its letters are wrong"
      }
      onClick={start}
    >
      {printed ? (run ? "Read again with Tesseract" : "Suggest labels (Tesseract)") : "Try Tesseract"}
    </button>
  );
  const booksButton = usable.length > 0 && (
    <button
      key="books"
      className={printed ? "" : "primary"}
      disabled={running || picked.size === 0}
      onClick={startBooks}
      title={`Each letter takes the label of the nearest labelled group in: ${usable
        .filter((r) => picked.has(r.id))
        .map((r) => r.name)
        .join(", ")}`}
    >
      {booksRun ? "Suggest again from labelled books" : "Suggest from labelled books"}
    </button>
  );

  return (
    <section className="suggest-bar" aria-label="Label suggestions">
      {dialog}
      <div className="suggest-actions">
        <strong className="small">Label suggestions</strong>
        {printed ? [tesseractButton, booksButton] : [booksButton, tesseractButton]}
        {run && printed && (
          <button disabled={running || !status?.ok} onClick={fixCuts} title="Split and join samples where Tesseract shows a wrong cut">
            Fix cuts with Tesseract
          </button>
        )}
        {printed && (
          <button disabled={running} onClick={fixBars} title="Give ા bars cut onto the next letter back to their letter (by shape)">
            Fix ા bars
          </button>
        )}
        {anyRun && (
          <button
            disabled={running}
            onClick={splitMixed}
            title="Letters of a group read as another letter, and shaped differently, go to a group of their own"
          >
            Split mixed groups
          </button>
        )}
        {anyRun && (
          <span className="row small bulk-accept">
            <button disabled={!candidates.length} onClick={acceptAll} title="Label every group whose suggestion has at least this share">
              Accept {candidates.length} with ≥
            </button>
            <input
              aria-label="Least share to accept"
              type="number"
              min={60}
              max={100}
              step={5}
              value={threshold}
              onChange={(e) => setThreshold(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
              className="share-input"
            />
            %
          </span>
        )}
        {running && (
          <button className="small" onClick={() => api.cancelJob(job!.id).then(setJob, setError)}>
            Cancel
          </button>
        )}
      </div>

      <div className="suggest-status small">
        <ErrorBox error={error} onClose={() => setError(null)} />
        {running && (
          <span className="row">
            <progress max={job!.total || 1} value={job!.done} />
            {job!.kind === "fix_cuts" ? "Checking cuts" : job!.kind === "fix_bars" ? "Checking pages" : "Reading"}:{" "}
            {job!.done} of {job!.total}
          </span>
        )}
        {status && !status.ok && <span className="error-text">{status.error}</span>}
        {job?.status === "failed" && <span className="error-text">{job.error}</span>}
        {job?.kind === "fix_cuts" && job.status === "done" && job.result && (
          <span>
            Fixed cuts: {String(job.result.splits)} split, {String(job.result.bars)} vowel bars put back,{" "}
            {String(job.result.joins)} joined. {String(job.result.placed)} of {String(job.result.samples_new)} new
            samples went into groups by their reading
            {Array.isArray(job.result.new_groups) && job.result.new_groups.length > 0
              ? ` (${job.result.new_groups.length} new groups, not reviewed yet)`
              : ""}
            ; the rest are in Unsure. Undo takes it all back.
          </span>
        )}
        {job?.kind === "fix_bars" && job.status === "done" && job.result && (
          <span>
            {Number(job.result.bars)
              ? `${job.result.bars} bars given back to their letter (${Number(job.result.joined) || 0} of them standing alone, like the stem of ણ): ${job.result.placed} new letters went into groups by shape, ${job.result.unsure} are in Unsure. Undo takes it all back.`
              : "No ા bar on the wrong letter found."}
            {Number(job.result.readings) > 0 && ` ${job.result.readings} letters made by the fix got back Tesseract's reading of the letters they replaced.`}
          </span>
        )}
        {splitNote && <span>{splitNote}</span>}
        {!running && (
          <span className="muted">
            {[lastRun(run, "Tesseract"), lastRun(booksRun, "Labelled books")].filter(Boolean).join(" · ") ||
              (printed
                ? "Not read yet: Tesseract reads the lines and suggests a label for each group."
                : usable.length
                  ? "Not read yet: your labelled books suggest labels by shape."
                  : "")}
          </span>
        )}
        {refs !== null && usable.length === 0 && !printed && (
          <span className="muted">
            No other book with labels {refs.length > 0 ? "that can be compared (other fingerprint settings)" : "yet"}:
            label some groups in another handwritten book to get suggestions from it.
          </span>
        )}
      </div>

      {(usable.length > 0 || accuracy.some((acc) => acc.suggested > 0)) && (
        <details className="suggest-details small">
          <summary>Details: reference books, accuracy</summary>
          <div className="suggest-details-body">
            {usable.length > 0 && (
              <fieldset className="plain">
                <legend className="muted">Learn from these labelled books</legend>
                {usable.map((r) => (
                  <label key={r.id} className="row">
                    <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} />
                    {r.name}{" "}
                    <span className="muted">
                      ({r.labelled} labelled{r.writing !== book.writing ? `, ${r.writing}` : ""})
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
            {accuracy
              .filter((acc) => acc.suggested > 0)
              .map((acc) => (
                <div key={acc.engine ?? ""}>
                  <span className="muted">
                    {acc.engine ? `${ENGINE_NAME[acc.engine]}: ` : ""}checked against your labels: {acc.right} of{" "}
                    {acc.suggested} right
                  </span>
                  <ul>
                    {acc.bands
                      .filter((b) => b.right + b.wrong > 0)
                      .map((b) => (
                        <li key={b.band}>
                          {b.band}: {b.right} of {b.right + b.wrong} right
                        </li>
                      ))}
                    <li>{acc.none} labelled groups would get no suggestion</li>
                    {acc.wrong.map((w) => (
                      <li key={w.label + w.suggested}>
                        {w.label} suggested as {w.suggested} ({w.groups})
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
          </div>
        </details>
      )}
    </section>
  );
}

/** The group's suggestion with Accept / Change / Reject (or Merge into the group with that label). */
export function SuggestionChip({ group, ctx, onChange }: { group: Group; ctx: ReviewContext; onChange: (guj: string) => void }) {
  const [dialog, confirm] = useConfirm();
  const sug = group.suggestion;
  if (!sug || group.label_dev) return null;
  const { bookId, act } = ctx;
  const into = sug.merge_into;
  const other = group.other_suggestion;

  async function merge() {
    if (into && (await confirm(`Merge ${group.code} (${group.samples} samples) into ${into.code}, labelled ${sug!.label_guj}?`, "Merge"))) {
      const r = await act(() => api.merge(bookId, into.id, [group.id]));
      if (r) go(`/books/${bookId}/review/${into.id}`);
    }
  }

  return (
    <div className="suggestion-chip" role="group" aria-label="Suggested label">
      {dialog}
      <span className="small muted">Suggested:</span> <span className="big-letter">{sug.label_guj}</span>{" "}
      <span className="muted">{sug.label_dev}</span>{" "}
      <span className="small muted">
        {sug.count} of {sug.read} read ({pct(sug.share)}) ·{" "}
        {sug.agree ? `${ENGINE_NAME[sug.agree[0]]} and ${ENGINE_NAME[sug.agree[1]]} agree` : `from ${ENGINE_NAME[sug.engine]}`}
      </span>
      <span className="row">
        {into ? (
          <button className="primary" disabled={group.locked} onClick={merge} title={`${into.code} already has this label`}>
            Merge into {into.code}
          </button>
        ) : (
          <button
            className="primary"
            disabled={group.locked}
            onClick={() => act(() => api.acceptSuggestions(bookId, [{ group_id: group.id, label_dev: sug.label_dev }]))}
          >
            Accept
          </button>
        )}
        <button disabled={group.locked} onClick={() => onChange(sug.label_guj)}>
          Change…
        </button>
        <button disabled={group.locked} onClick={() => act(() => api.rejectSuggestion(bookId, group.id, sug.label_dev))}>
          Reject
        </button>
      </span>
      {other && (
        <span className="small other-suggestion">
          {ENGINE_NAME[other.engine]} suggest{other.engine === "tesseract" ? "s" : ""} <strong>{other.label_guj}</strong>{" "}
          <span className="muted">
            {other.label_dev} · {other.count} of {other.read} ({pct(other.share)})
          </span>{" "}
          {!other.merge_into && (
            <button
              className="link"
              disabled={group.locked}
              onClick={() => act(() => api.acceptSuggestions(bookId, [{ group_id: group.id, label_dev: other.label_dev }]))}
            >
              Accept this instead
            </button>
          )}
        </span>
      )}
    </div>
  );
}

/** What the group's samples were read as; "select" picks all samples of one reading (every page). */
export function ReadingsLine({ group, ctx }: { group: Group; ctx: ReviewContext }) {
  const [error, setError] = useState<unknown>(null);
  if (group.readings.length === 0) return null;
  const expected = expectedReading(group);
  const mixed = isMixed(group);
  if (!mixed && group.readings.length === 1 && group.readings[0].label_dev === expected) return null;

  async function selectRead(text: string) {
    try {
      const { ids } = await api.readAs(group.id, text);
      ctx.setSelection({ ids: new Set(ids), anchor: null });
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="readings small">
      <ErrorBox error={error} onClose={() => setError(null)} />
      <span className="muted">{mixed ? "Mixed readings — " : ""}Read as:</span>
      {group.readings.map((r) => (
        <button key={r.label_dev} className="link" onClick={() => selectRead(r.label_dev)} title="Select these samples">
          {r.label_guj} <span className="muted">{r.count}</span>
        </button>
      ))}
      <span className="muted">
        of {group.read} read.{mixed && " Click a reading to select its samples, then New group or To Unsure to split the group."}
      </span>
    </div>
  );
}
