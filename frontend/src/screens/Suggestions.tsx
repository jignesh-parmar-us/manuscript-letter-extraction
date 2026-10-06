// Label suggestions in the Review tab (C12).
// - SuggestPanel (in the side bar): read the book with Tesseract (a background job), accept all
//   suggestions above a share in one undoable step, and see how the suggestions compare with the
//   labels given so far. On printed books, "Fix cuts with Tesseract" splits samples that hold several
//   letters and joins letters cut in pieces (C12b), as one undoable step.
// - SuggestionChip (on a group): accept, change or reject its suggestion; or merge into the group
//   that already has the suggested label.
// - ReadingsLine (on a group): what its samples were read as; select the samples of one reading to
//   split a mixed group.
// A suggestion never labels a group by itself: every accept is a normal, undoable action.
import { useCallback, useEffect, useState } from "react";
import { api, Book, Group, Job, localTime, SuggestionAccuracy, TesseractStatus } from "../api";
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
  const [accuracy, setAccuracy] = useState<SuggestionAccuracy | null>(null);
  const [threshold, setThreshold] = useState(() => Math.round(100 * Number(book.settings.bulk_accept_share ?? 0.9)));
  const [dialog, confirm] = useConfirm();
  const onEnd = useCallback(
    (j: Job) => {
      if (j.status === "done") onRead();
    },
    [onRead],
  );
  const [job, setJob] = useJob(book.job?.kind === "suggest" || book.job?.kind === "fix_cuts" ? book.job : null, onEnd);
  const run = book.ocr_runs?.find((r) => r.engine === "tesseract");
  const printed = book.writing === "printed";

  useEffect(() => {
    api.tesseract(book.id).then(setStatus, setError);
  }, [book.id]);
  const runTime = run?.finished_at;
  useEffect(() => {
    if (!runTime || book.labelled === 0) setAccuracy(null);
    else api.accuracy(book.id).then(setAccuracy, () => setAccuracy(null));
  }, [book.id, book.labelled, runTime, ctx.version]);

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
  return (
    <div className="card subtle suggest-panel">
      {dialog}
      <strong className="small">Label suggestions</strong>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {!printed && (
        <p className="small muted">
          This book is handwritten. Tesseract reads print; on handwriting about a third of its letters are wrong, so
          check its suggestions closely.
        </p>
      )}
      <div className="row">
        <button
          className={printed ? "primary" : ""}
          disabled={running || !status?.ok}
          title={status && !status.ok ? status.error : undefined}
          onClick={start}
        >
          {printed ? (run ? "Read again with Tesseract" : "Suggest labels (Tesseract)") : "Try Tesseract"}
        </button>
        {running && (
          <button className="small" onClick={() => api.cancelJob(job!.id).then(setJob, setError)}>
            Cancel
          </button>
        )}
      </div>
      {status && !status.ok && <p className="small error-text">{status.error}</p>}
      {running && (
        <div className="small">
          <progress max={job!.total || 1} value={job!.done} />
          {job!.kind === "fix_cuts" ? "Checking cuts" : "Reading lines"}: {job!.done} of {job!.total}
        </div>
      )}
      {job?.status === "failed" && <p className="small error-text">{job.error}</p>}
      {job?.kind === "fix_cuts" && job.status === "done" && job.result && (
        <p className="small">
          Fixed cuts: {String(job.result.splits)} split, {String(job.result.bars)} vowel bars put back,{" "}
          {String(job.result.joins)} joined. {String(job.result.placed)} of {String(job.result.samples_new)} new
          samples went into groups by their reading
          {Array.isArray(job.result.new_groups) && job.result.new_groups.length > 0
            ? ` (${job.result.new_groups.length} new groups, not reviewed yet)`
            : ""}
          ; the rest are in Unsure. Undo takes it all back.
        </p>
      )}
      {run && !running && (
        <p className="small muted">
          Read {localTime(run.finished_at)}: {run.result.samples_matched} of {run.result.samples} letters,{" "}
          {run.result.groups_with_suggestion} groups with a suggestion.
        </p>
      )}
      {run && printed && (
        <button disabled={running || !status?.ok} onClick={fixCuts} title="Split and join samples where Tesseract shows a wrong cut">
          Fix cuts with Tesseract
        </button>
      )}
      {run && (
        <div className="row small bulk-accept">
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
        </div>
      )}
      {accuracy && accuracy.suggested > 0 && (
        <details className="small">
          <summary>
            Checked against your labels: {accuracy.right} of {accuracy.suggested} right
          </summary>
          <ul>
            {accuracy.bands
              .filter((b) => b.right + b.wrong > 0)
              .map((b) => (
                <li key={b.band}>
                  {b.band}: {b.right} of {b.right + b.wrong} right
                </li>
              ))}
            <li>{accuracy.none} labelled groups would get no suggestion</li>
            {accuracy.wrong.map((w) => (
              <li key={w.label + w.suggested}>
                {w.label} suggested as {w.suggested} ({w.groups})
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** The group's suggestion with Accept / Change / Reject (or Merge into the group with that label). */
export function SuggestionChip({ group, ctx, onChange }: { group: Group; ctx: ReviewContext; onChange: (guj: string) => void }) {
  const [dialog, confirm] = useConfirm();
  const sug = group.suggestion;
  if (!sug || group.label_dev) return null;
  const { bookId, act } = ctx;
  const into = sug.merge_into;

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
        {sug.count} of {sug.read} read ({pct(sug.share)})
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
