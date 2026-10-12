// "Pages & capture" tab: cut the book's pages into letters (capture), follow the progress,
// add new pages, cut a single page again, and the settings used for that.
import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, AppInfo, Book, Job, localTime, PageInfo, PageProblem, Writing } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import FolderField from "../components/FolderField";
import { useJob } from "../components/useJob";
import WritingChoice from "../components/WritingChoice";

interface Props {
  book: Book;
  info: AppInfo | null;
  onChanged: () => void;
}

export const JOB_NAMES: Record<Job["kind"], string> = {
  capture: "Capture",
  add_pages: "Adding new pages",
  recut_page: "Cutting a page again",
  export: "Export",
  suggest: "Reading with Tesseract",
  fix_cuts: "Fixing cuts with Tesseract",
  fix_bars: "Giving ા bars back to their letters",
  capture_read: "Cutting the Read Book pages",
  import_pdf: "Turning the PDF into page images",
  convert: "Converting pages into text",
  line_search: "Our reader (line search)",
  line_search_measure: "Measuring our reader on the checked lines",
  line_search_train: "Training our reader (reviewed letters and checked lines)",
  train: "Training a letter reader",
  use_reader: "Reading with the letter reader",
  generate_letters: "Making the missing letters",
  top_up: "Making variants for small groups",
};

export default function Capture({ book, info, onChanged }: Props) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [problems, setProblems] = useState<PageProblem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();

  const loadPages = useCallback(() => {
    api.pages(book.id).then(setPages, setError);
    api.pageProblems(book.id).then(setProblems, setError);
  }, [book.id]);
  useEffect(loadPages, [loadPages]);

  const onEnd = useCallback(() => {
    loadPages();
    onChanged();
  }, [loadPages, onChanged]);
  const [job, setJob] = useJob(book.job, onEnd);

  /** Start a job; if the backend says it would discard manual work, ask, then repeat with force. */
  async function start(run: (force: boolean) => Promise<Job>, question: string) {
    setError(null);
    try {
      setJob(await run(false));
    } catch (e) {
      if (e instanceof ApiError && e.needsConfirmation && (await confirm(`${e.message} ${question}`, "Continue"))) {
        try {
          setJob(await run(true));
        } catch (e2) {
          setError(e2);
        }
      } else if (!(e instanceof ApiError && e.needsConfirmation)) {
        setError(e);
      }
    }
  }

  const cutMethod = (book.settings.cut_method as string) === "tesseract" ? "tesseract" : "shapes";
  async function changeCut(method: "shapes" | "tesseract") {
    try {
      await api.setSettings(book.id, { ...book.settings, cut_method: method });
      onChanged();
    } catch (e) {
      setError(e);
    }
  }

  async function changeWriting(writing: Writing) {
    try {
      await api.setWriting(book.id, writing);
      onChanged();
    } catch (e) {
      setError(e);
    }
  }

  const running = job?.status === "running";
  const newPages = problems.filter((p) => p.problem === "new");
  const otherProblems = problems.filter((p) => p.problem !== "new");

  return (
    <div>
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />

      <div className="card">
        <PageFolder book={book} info={info} onChanged={onEnd} onError={setError} />
        {book.input_dir && <p className="small">Last capture: {localTime(book.captured_at)}</p>}
        <WritingChoice value={book.writing} onChange={changeWriting} />
        {(book.writing === "printed" || cutMethod === "tesseract") && (
          <fieldset className="plain">
            <legend className="small muted">Cutting into letters</legend>
            <label className="row small">
              <input type="radio" name="cut" checked={cutMethod === "shapes"} onChange={() => changeCut("shapes")} />
              <strong>By the shapes of the ink</strong> <span className="muted">works for handwriting and print</span>
            </label>
            <label className="row small">
              <input type="radio" name="cut" checked={cutMethod === "tesseract"} onChange={() => changeCut("tesseract")} />
              <strong>By Tesseract's reading</strong>{" "}
              <span className="muted">printed books: each line is cut into the letters Tesseract reads, which also become their readings</span>
            </label>
            <p className="small muted">The choice is used the next time the pages are captured or cut again.</p>
          </fieldset>
        )}
        <div className="row">
          <button
            className="primary"
            disabled={running || !book.input_dir}
            onClick={() => start((force) => api.capture(book.id, force), "Capture anyway?")}
          >
            {book.captured_at ? "Capture again" : "Capture letters"}
          </button>
          <button disabled={running || newPages.length === 0} onClick={() => start(() => api.addPages(book.id), "")}>
            Add new pages{newPages.length > 0 && ` (${newPages.length})`}
          </button>
        </div>
        {otherProblems.length > 0 && (
          <ul className="warnings small">
            {otherProblems.map((p) => (
              <li key={p.file}>
                {p.file}: {p.problem === "missing" ? "the image file is missing" : "the image file has changed since capture"}
              </li>
            ))}
          </ul>
        )}
      </div>

      {job && <JobPanel job={job} onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}

      <Settings book={book} onSaved={onChanged} onError={setError} />

      {pages.length > 0 && (
        <table className="list">
          <thead>
            <tr>
              <th>Page</th>
              <th>Status</th>
              <th className="num">Lines</th>
              <th className="num">Letters</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr key={p.id}>
                <td>{p.file}</td>
                <td>
                  <span className={p.status === "OK" ? "badge ok" : "badge warn"}>{p.status}</span>{" "}
                  <span className="muted small">{p.message}</span>
                </td>
                <td className="num">{p.lines}</td>
                <td className="num">{p.samples}</td>
                <td className="actions">
                  <button
                    disabled={running}
                    onClick={() =>
                      start((force) => api.recutPage(book.id, p.id, force), "Cut this page again anyway?")
                    }
                  >
                    Cut again
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** The folder of the Training Data page images: chosen here, not when the book is made, since a book
 * read only by Tesseract (Read Book) needs none. */
function PageFolder(props: { book: Book; info: AppInfo | null; onChanged: () => void; onError: (e: unknown) => void }) {
  const { book } = props;
  const [editing, setEditing] = useState(false);
  const [folder, setFolder] = useState(book.input_dir);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api.setInputFolder(book.id, folder.trim());
      setEditing(false);
      props.onChanged();
    } catch (err) {
      props.onError(err);
    }
  }

  if (book.input_dir && !editing) {
    return (
      <p className="small">
        Page images: <code>{book.input_dir}</code>{" "}
        <button className="link" onClick={() => setEditing(true)}>
          Change…
        </button>
      </p>
    );
  }
  return (
    <form onSubmit={save}>
      {!book.input_dir && (
        <p className="small muted">
          Choose the folder with the Training Data page images, to cut them into letters. A book read only by Tesseract
          (Read Book) needs none.
        </p>
      )}
      <FolderField label="Folder with the page images" value={folder} onChange={setFolder} info={props.info} />
      {book.input_dir && (
        <p className="small muted">
          The pages already captured are looked for in the new folder by their file names.
        </p>
      )}
      <div className="row">
        <button type="submit" disabled={!folder.trim()}>
          Use this folder
        </button>
        {book.input_dir && (
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              setFolder(book.input_dir);
            }}
          >
            Cancel
          </button>
        )}
      </div>
      <p className="muted small">The page images are only read, never changed.</p>
    </form>
  );
}

export function JobPanel({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const pct = job.total > 0 ? Math.round((100 * job.done) / job.total) : 0;
  const result = job.result as Record<string, number> | null;
  return (
    <div className="card" aria-live="polite">
      <div className="row between">
        <strong>
          {JOB_NAMES[job.kind]}:{" "}
          {job.status === "running"
            ? `${job.done} of ${job.total} pages`
            : job.status === "done"
              ? "finished"
              : job.status === "cancelled"
                ? "cancelled, nothing was changed"
                : "failed"}
        </strong>
        <span className="muted small">{job.seconds} s</span>
      </div>
      {job.status === "running" && (
        <>
          <progress max={job.total || 1} value={job.done} aria-label="Progress">
            {pct}%
          </progress>
          <div className="row between small">
            <span className="muted">{job.current ? `Last page: ${job.current}` : "Cutting the first pages…"}</span>
            <button onClick={onCancel}>Cancel</button>
          </div>
        </>
      )}
      {job.status === "failed" && <p className="error">{job.error}</p>}
      {job.status === "done" && result && job.kind === "convert" && (
        <p className="small">
          {result.pages} pages converted: {result.letters} letters, {result.uncertain} uncertain
        </p>
      )}
      {job.status === "done" && result && job.kind === "line_search" && (
        <p className="small">
          {result.pages} pages, {result.lines} lines read by our reader; where it reads an akshara differently from
          Tesseract, the akshara is marked uncertain in both views
        </p>
      )}
      {job.status === "done" && result && job.kind === "line_search_measure" && (
        <p className="small">
          {result.lines} checked lines: our reader {(result.cer as unknown as { ours: number }).ours}% of the characters
          wrong, Tesseract {(result.cer as unknown as { tesseract: number }).tesseract}%
        </p>
      )}
      {job.status === "done" && result && job.kind === "line_search_train" && (
        <p className="small">
          Our reader learned {result.letters} reviewed letters and {(result as unknown as { lines: number }).lines} checked
          lines. Read the pages again to use it.
        </p>
      )}
      {job.status === "done" && result && job.kind !== "convert" && job.kind !== "line_search" &&
        job.kind !== "line_search_measure" && job.kind !== "line_search_train" && (
        <p className="small">
          {result.pages} pages, {result.lines} lines, {result.samples} letters
          {"groups" in result && `, ${result.groups} groups, ${result.unsure} unsure`}
          {"labelled_groups" in result &&
            `. Labelled from Tesseract's reading: ${result.labelled_groups} groups` +
              (Number(result.placed) > 0 ? `, ${result.placed} unsure letters placed` : "") +
              " (not reviewed yet)"}
        </p>
      )}
      {job.pages.some((p) => p.status !== "OK") && (
        <ul className="warnings small">
          {job.pages
            .filter((p) => p.status !== "OK")
            .map((p) => (
              <li key={p.file}>
                {p.file}: {p.status} {p.message}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function Settings({ book, onSaved, onError }: { book: Book; onSaved: () => void; onError: (e: unknown) => void }) {
  async function load(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const settings = JSON.parse(await file.text());
      await api.setSettings(book.id, settings);
      onSaved();
    } catch (err) {
      onError(err instanceof SyntaxError ? new Error(`${file.name} is not a JSON file: ${err.message}`) : err);
    }
  }
  async function reset() {
    try {
      await api.setSettings(book.id, null);
      onSaved();
    } catch (err) {
      onError(err);
    }
  }
  return (
    <details className="card subtle">
      <summary>Settings for the next capture</summary>
      <p className="small muted">
        Most books work with the defaults. A settings file (JSON) names the values that differ from the defaults, for
        example <code>{'{"group_distance": 0.6, "digits": "western"}'}</code>; every other value is the default. Letters
        already in the book do not change until the pages are captured or cut again.
      </p>
      <div className="row">
        <label className="button">
          Load settings file…
          <input type="file" accept=".json,application/json" onChange={load} hidden />
        </label>
        <button onClick={reset}>Back to the defaults</button>
      </div>
      <pre className="settings">{JSON.stringify(book.settings, null, 2)}</pre>
    </details>
  );
}
