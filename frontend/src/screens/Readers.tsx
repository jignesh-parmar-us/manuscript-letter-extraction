// Training Data → Letter checker (C14; "Readers" until C19): train a letter checker on the reviewed letters,
// as often as wanted; every training makes a new checker, kept with its report (accuracy on pages it did not
// learn from, per letter, the most confused pairs, the letters left out). One checker is the book's active
// one: it reads the book's letters for suggestions and "Check these" in Review groups. It does not read books
// (that is our reader, Read Book → Text).
import { useCallback, useEffect, useState } from "react";
import { api, Book, BookSummary, localTime, ReaderInfo } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import { toGujarati } from "../components/LabelPicker";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(100 * v).toFixed(1)}%`);

interface Props {
  book: Book;
  onChanged: () => void;
}

export default function Readers({ book, onChanged }: Props) {
  const [readers, setReaders] = useState<ReaderInfo[]>([]);
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set([book.id]));
  const [minSamples, setMinSamples] = useState(5);
  const [unreviewed, setUnreviewed] = useState(false);
  const [words, setWords] = useState(false);
  const [open, setOpen] = useState<ReaderInfo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();

  const load = useCallback(() => {
    api.readers().then(setReaders, setError);
    api.books().then((bs) => setBooks(bs.filter((b) => b.writing === book.writing)), setError);
  }, [book.writing]);
  useEffect(load, [load]);
  const onEnd = useCallback(() => {
    load();
    onChanged();
  }, [load, onChanged]);
  const [job, setJob] = useJob(book.job && ["train", "use_reader"].includes(book.job.kind) ? book.job : null, onEnd);
  const running = job?.status === "running";

  async function train() {
    setError(null);
    try {
      setJob(await api.train(book.id, { books: [...chosen], min_samples: minSamples, include_unreviewed: unreviewed,
        include_words: words }));
    } catch (e) {
      setError(e);
    }
  }
  async function use(id: number | null) {
    try {
      setJob(await api.useReader(book.id, id));
    } catch (e) {
      setError(e);
    }
  }
  async function remove(r: ReaderInfo) {
    if (!(await confirm(`Delete ${r.name}? Books that use it will have no active letter checker.`, "Delete"))) return;
    try {
      await api.deleteReader(r.id);
      if (open?.id === r.id) setOpen(null);
      onEnd();
    } catch (e) {
      setError(e);
    }
  }
  async function report(r: ReaderInfo) {
    try {
      setOpen(open?.id === r.id ? null : await api.reader(r.id));
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="readers">
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="card">
        <h2>Letter checker</h2>
        <p>
          Finds letters that are probably in the wrong group (<em>Check these</em> in Review groups) and suggests labels.
          It does not read books: that is our reader, in Read Book → Text.
        </p>
        <p className="small muted">
          The checker learns the letters of your reviewed groups and is tested on pages it did not learn from. Train again
          whenever you have reviewed or corrected more: every training makes a new checker, and older ones are kept.
        </p>
        <fieldset className="plain">
          <legend className="small muted">Learn from (books with the same writing)</legend>
          {books.map((b) => (
            <label key={b.id} className="row small">
              <input
                type="checkbox"
                checked={chosen.has(b.id)}
                onChange={() => {
                  const next = new Set(chosen);
                  if (next.has(b.id)) next.delete(b.id);
                  else next.add(b.id);
                  setChosen(next);
                }}
              />
              {b.name} <span className="muted">({b.reviewed} reviewed letters)</span>
            </label>
          ))}
        </fieldset>
        <div className="row small train-options">
          <label className="row">
            A label needs at least
            <input
              aria-label="Least letters a label needs"
              type="number"
              min={1}
              max={100}
              value={minSamples}
              onChange={(e) => setMinSamples(Math.max(1, Number(e.target.value) || 1))}
              className="share-input"
            />
            letters
          </label>
          <label className="row" title="Labels given automatically (capture, suggestions) and not reviewed yet: a wrong one teaches a wrong letter">
            <input type="checkbox" checked={unreviewed} onChange={(e) => setUnreviewed(e.target.checked)} />
            also groups not reviewed
          </label>
          <label className="row">
            <input type="checkbox" checked={words} onChange={(e) => setWords(e.target.checked)} />
            also word labels
          </label>
        </div>
        {minSamples < 5 && (
          <p className="small muted">
            Labels with fewer than 5 letters are learned too, but their accuracy cannot be measured and they stay weak until
            they have more letters.
          </p>
        )}
        <button className="primary" disabled={running || chosen.size === 0} onClick={train}>
          Train
        </button>
      </div>

      {job && <JobPanel job={job} onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}

      {readers.length > 0 && (
        <table className="list" aria-label="Letter checkers">
          <thead>
            <tr>
              <th>Checker</th>
              <th>Trained</th>
              <th className="num">Letters</th>
              <th className="num">Labels</th>
              <th className="num" title="On pages it did not learn from">Accuracy</th>
              <th className="num" title="Labels with 20 or more letters">20+</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {readers.map((r) => (
              <tr key={r.id} className={r.id === book.reader_id ? "active-row" : ""}>
                <td>
                  <strong>{r.name}</strong>
                  {r.id === book.reader_id && <span className="badge ok"> active</span>}
                  <div className="muted small">{(r.trained_on.book_names ?? []).join(", ")}</div>
                </td>
                <td className="small">{localTime(r.created_at)}</td>
                <td className="num">{r.trained_on.letters}</td>
                <td className="num">{r.labels}</td>
                <td className="num">{pct(r.accuracy)}</td>
                <td className="num">{pct(r.accuracy_20)}</td>
                <td className="actions">
                  <button onClick={() => report(r)}>{open?.id === r.id ? "Hide report" : "Report"}</button>
                  {r.id === book.reader_id ? (
                    <button disabled={running} onClick={() => use(null)}>
                      Stop using
                    </button>
                  ) : (
                    <button disabled={running} onClick={() => use(r.id)}>
                      Use for this book
                    </button>
                  )}
                  <button className="danger" onClick={() => remove(r)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {readers.length === 0 && !job && <p className="muted">No letter checker trained yet.</p>}

      {open && <Report reader={open} book={book} />}
    </div>
  );
}

function Report({ reader, book }: { reader: ReaderInfo; book: Book }) {
  const left = reader.trained_on.left_out ?? [];
  return (
    <div className="card reader-report" aria-label="Report">
      <h3>{reader.name}</h3>
      <p className="small">
        Tested on {reader.trained_on.test_letters} letters of {reader.trained_on.test_pages} pages it did not learn from:{" "}
        <strong>{pct(reader.accuracy)}</strong> read right ({pct(reader.accuracy_20)} for labels with 20 or more letters).
        Trained on {reader.trained_on.letters} letters, {reader.labels} labels, in {reader.seconds} s.
        {reader.id === book.reader_id && reader.check !== undefined && (
          <>
            {" "}
            <button className="link" onClick={() => go(`/books/${book.id}/review/check`)}>
              {reader.check} letters to check
            </button>{" "}
            (probably in the wrong group).
          </>
        )}
      </p>
      {(reader.confusions ?? []).length > 0 && (
        <p className="small">
          Most confused:{" "}
          {(reader.confusions ?? []).slice(0, 12).map(([a, b, n], i) => (
            <span key={i} className="confusion">
              {toGujarati(a)} → {toGujarati(b)} ({n}){" "}
            </span>
          ))}
        </p>
      )}
      <table className="list compact" aria-label="Accuracy per letter">
        <thead>
          <tr>
            <th>Letter</th>
            <th className="num">Letters</th>
            <th className="num">Tested</th>
            <th className="num">Accuracy</th>
          </tr>
        </thead>
        <tbody>
          {(reader.per_label ?? []).map((r) => (
            <tr key={r.label}>
              <td className="big-letter-cell">{toGujarati(r.label)}</td>
              <td className="num">{r.letters}</td>
              <td className="num">{r.tested}</td>
              <td className="num">{r.accuracy === null ? <span className="muted">not measured</span> : pct(r.accuracy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {left.length > 0 && (
        <p className="small muted">
          Left out ({left.length} labels with fewer than {reader.trained_on.min_samples} letters):{" "}
          {left.slice(0, 60).map(([l, n]) => `${toGujarati(l)} (${n})`).join(" · ")}
          {left.length > 60 && " …"}
        </p>
      )}
    </div>
  );
}
