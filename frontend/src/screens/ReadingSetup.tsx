// Read Book → Reading setup (C23): what the book reads with. 1. the datasets its reading model learns from
// (added, removed, opened; a dataset of another writing is allowed but warned about), 2. the word lists (the old
// Dictionary tab, unchanged inside), 3. the reading model: what our reader was trained on, out of date when the
// datasets' reviewed letters or the checked lines changed since, Train / Retrain and Measure.
import { useCallback, useEffect, useState } from "react";
import { api, Book, localTime, ReadingSetupInfo, WRITING_LABEL } from "../api";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";
import Dictionary from "./Dictionary";

interface Props {
  book: Book;
  onChanged: () => void;
}

const MODEL_JOBS = ["line_search_train", "line_search_measure"];

export default function ReadingSetup({ book, onChanged }: Props) {
  const [setup, setSetup] = useState<ReadingSetupInfo | null>(null);
  const [adding, setAdding] = useState<number | "">("");
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
          </p>
        )}
        {job && <JobPanel job={job} reading onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}
        {setup.model && <p className="small muted">Kept in <code>{setup.model.folder}</code></p>}
      </section>
    </div>
  );
}
