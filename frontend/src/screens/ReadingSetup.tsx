// Read Book → Reading setup (C23): what the book reads with. 1. the datasets its reading model learns from
// (added, removed, opened; a dataset of another writing is allowed but warned about), 2. the word lists (the old
// Dictionary tab, unchanged inside), 3. the reading model: what our reader was trained on, out of date when the
// datasets' reviewed letters or the checked lines changed since, Train / Retrain and Measure. 4. the Tesseract model
// (C30c): Standard or one trained on a book's checked lines (this book's or another's), and training this book's.
import { useCallback, useEffect, useState } from "react";
import { api, Book, localTime, ReadingSetupInfo, TesseractModel, WRITING_LABEL } from "../api";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";
import Dictionary from "./Dictionary";

interface Props {
  book: Book;
  onChanged: () => void;
}

const MODEL_JOBS = ["line_search_train", "line_search_measure", "tesseract_train"];

export default function ReadingSetup({ book, onChanged }: Props) {
  const [setup, setSetup] = useState<ReadingSetupInfo | null>(null);
  const [adding, setAdding] = useState<number | "">("");
  const [startBook, setStartBook] = useState(0);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.readingSetup(book.id).then(setSetup, setError);
  }, [book.id]);
  useEffect(load, [load]);
  const onEnd = useCallback(() => {
    load();
    onChanged();
  }, [load, onChanged]);
  const [job, setJob] = useJob(book.job && MODEL_JOBS.includes(book.job.kind) ? book.job : null, onEnd);
  const running = job?.status === "running" || (book.job?.status === "running" && !job);

  async function choose(ids: number[]) {
    setError(null);
    try {
      setSetup(await api.setBookDatasets(book.id, ids));
      setAdding("");
      onChanged();
    } catch (e) {
      setError(e);
    }
  }
  async function chooseTesseract(bookId: number) {
    setError(null);
    try {
      setSetup(await api.setTesseractModel(book.id, bookId));
      onChanged();
    } catch (e) {
      setError(e);
    }
  }
  async function start(run: () => Promise<import("../api").Job>) {
    setError(null);
    try {
      setJob(await run());
    } catch (e) {
      setError(e);
    }
  }

  if (!setup) return <ErrorBox error={error} onClose={() => setError(null)} />;
  const used = setup.datasets.map((d) => d.id);
  const reader = setup.reader;
  const m = setup.measure;
  const tess = setup.tesseract;
  const tessJob = job?.kind === "tesseract_train";

  return (
    <div className="reading-setup">
      <ErrorBox error={error} onClose={() => setError(null)} />

      <section className="card" aria-label="Datasets used">
        <h2>1. Datasets used</h2>
        <p className="small muted">
          Our reader learns the reviewed letters of these datasets, the language model their labels. Removing one from this
          book leaves the dataset itself as it is.
        </p>
        {setup.datasets.length === 0 ? (
          <p className="small warn-text">No dataset yet: our reader needs the reviewed letters of at least one.</p>
        ) : (
          <table className="list" aria-label="Datasets used">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Writing</th>
                <th className="num">Pages</th>
                <th className="num">Reviewed letters</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {setup.datasets.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>
                    {WRITING_LABEL[d.writing]}
                    {d.writing !== setup.writing && (
                      <div className="small warn-text">the book is {WRITING_LABEL[setup.writing].toLowerCase()}</div>
                    )}
                  </td>
                  <td className="num">{d.pages}</td>
                  <td className="num">{d.reviewed}</td>
                  <td className="actions">
                    <button onClick={() => go(`/books/${d.id}`)}>Open</button>
                    <button disabled={running} onClick={() => choose(used.filter((x) => x !== d.id))}>
                      Remove from this book
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row">
          <select aria-label="Dataset to add" value={adding} disabled={running || setup.others.length === 0}
            onChange={(e) => setAdding(e.target.value ? Number(e.target.value) : "")}>
            <option value="">{setup.others.length ? "choose a dataset…" : "no other dataset"}</option>
            {setup.others.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({WRITING_LABEL[d.writing]}, {d.reviewed} reviewed letters)
                {d.writing !== setup.writing ? " ⚠ other writing" : ""}
              </option>
            ))}
          </select>
          <button disabled={running || adding === ""} onClick={() => adding !== "" && choose([...used, adding])}>
            Add dataset
          </button>
          <button className="link" onClick={() => go("/datasets")}>
            New dataset…
          </button>
        </div>
      </section>

      <section aria-label="Word lists">
        <h2 className="setup-part">2. Word lists and the language model</h2>
        <Dictionary book={book} onChanged={onChanged} />
      </section>

      <section className="card" aria-label="Reading model">
        <h2>3. Reading model</h2>
        {reader ? (
          <p className="small">
            Our reader was trained {localTime(reader.trained_at)} on {reader.letters.toLocaleString()} reviewed letters
            ({reader.labels} labels) and {reader.lines} checked lines.{" "}
            {reader.changed ? (
              <span className="badge warn">out of date</span>
            ) : (
              <span className="badge ok">up to date</span>
            )}
          </p>
        ) : (
          <p className="small muted">Our reader is not trained yet.</p>
        )}
        {reader?.changed && (
          <p className="small muted">The datasets, their reviewed letters or the checked lines changed since: retrain to use them.</p>
        )}
        <p className="small muted">The language model follows the datasets and word lists by itself.</p>
        <div className="row">
          <button className={!reader || reader.changed ? "primary" : undefined}
            disabled={running || setup.datasets.length === 0} onClick={() => start(() => api.lineSearchTrain(book.id))}>
            {reader ? "Retrain" : "Train"}
          </button>
          <button disabled={running || setup.datasets.length === 0} onClick={() => start(() => api.lineSearchMeasure(book.id))}
            title="Fold-fair on the checked lines (Line truth): takes a while">
            Measure
          </button>
        </div>
        {m && (
          <p className="small">
            Last measure ({localTime(m.measured_at)}, {m.lines} checked lines on {m.pages} pages): characters wrong, our reader{" "}
            <strong>{m.cer.ours}%</strong>, Tesseract {m.cer.tesseract}%, Tesseract + language model {m.cer.tesseract_lm}%.
            {m.tesseract_fair === false && (
              <span className="warn-text"> Tesseract's numbers are not fold-fair: it read with a model trained on these checked lines.</span>
            )}
          </p>
        )}
        {job && !tessJob && <JobPanel job={job} reading onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}
        {setup.model && <p className="small muted">Kept in <code>{setup.model.folder}</code></p>}
      </section>

      <section className="card" aria-label="Tesseract model">
        <h2>4. Tesseract model</h2>
        <p className="small muted">
          Tesseract reads the whole lines. Standard Tesseract knows Devanagari in general; a model trained on a book's checked
          lines knows its print. A book in a similar print can read with another book's model.
        </p>
        <div className="row">
          <label>
            Read with{" "}
            <select aria-label="Tesseract model to read with" value={tess.using} disabled={running}
              onChange={(e) => chooseTesseract(Number(e.target.value))}>
              <option value={0}>Standard Tesseract</option>
              {tess.models.map((t) => (
                <option key={t.book_id} value={t.book_id}>
                  {modelLabel(t, book.id)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="small muted">Read the pages again to use a newly chosen model.</p>
        {tess.using === book.id && (
          <p className="small warn-text">
            This model learnt this book's checked lines, so Measure's Tesseract numbers are not fold-fair; the fair number
            comes from training it once per fold (tools/tesstrain/score.py).
          </p>
        )}
        <h3>This book's model</h3>
        {tess.own ? (
          <p className="small">
            Trained {localTime(tess.own.trained_at)} on {tess.own.lines} checked lines ({tess.own.epochs} epochs, from{" "}
            {tess.own.start_name}){tess.own.training_error !== null && <>, error on its own lines {tess.own.training_error}%</>}.{" "}
            {tess.own.changed ? <span className="badge warn">out of date</span> : <span className="badge ok">up to date</span>}
          </p>
        ) : (
          <p className="small muted">Not trained yet. It learns from the checked lines (Line truth); about 100 of them is a good start.</p>
        )}
        {!tess.tools_ok && (
          <p className="small warn-text">
            The training programs are not in <code>{tess.tools}</code>: run tools/tesstrain/setup.sh (docs/INSTALL_TESSERACT.md).
          </p>
        )}
        <div className="row">
          <label>
            Start from{" "}
            <select aria-label="Start from" value={startBook} disabled={running} onChange={(e) => setStartBook(Number(e.target.value))}>
              <option value={0}>Standard Tesseract</option>
              {tess.models.filter((t) => t.book_id !== book.id).map((t) => (
                <option key={t.book_id} value={t.book_id}>
                  {modelLabel(t, book.id)}
                </option>
              ))}
            </select>
          </label>
          <button disabled={running || !tess.tools_ok} title="A heavy job: about 10 minutes for 100 lines"
            onClick={() => start(() => api.tesseractTrain(book.id, startBook))}>
            {tess.own ? "Retrain Tesseract" : "Train Tesseract"}
          </button>
        </div>
        {job && tessJob && <JobPanel job={job} reading onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}
      </section>
    </div>
  );
}

function modelLabel(t: TesseractModel, bookId: number): string {
  const whose = t.book_id === bookId ? "this book" : t.book_name;
  return `Trained on ${whose} (${localTime(t.trained_at)}, ${t.lines} lines)${t.changed ? ", out of date" : ""}`;
}
