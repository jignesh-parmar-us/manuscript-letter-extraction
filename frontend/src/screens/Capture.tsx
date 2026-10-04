// "Pages & capture" tab: cut the book's pages into letters (capture), follow the progress,
// add new pages, cut a single page again, and the settings used for that.
import { ChangeEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, AppInfo, Book, Job, localTime, PageInfo, PageProblem } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";

interface Props {
  book: Book;
  info: AppInfo | null;
  onChanged: () => void;
}

const JOB_NAMES: Record<Job["kind"], string> = {
  capture: "Capture",
  add_pages: "Adding new pages",
  recut_page: "Cutting a page again",
};

export default function Capture({ book, onChanged }: Props) {
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

  const running = job?.status === "running";
  const newPages = problems.filter((p) => p.problem === "new");
  const otherProblems = problems.filter((p) => p.problem !== "new");

  return (
    <div>
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />

      <div className="card">
        <p className="small">
          Page images: <code>{book.input_dir}</code>
          <br />
          Last capture: {localTime(book.captured_at)}
        </p>
        <div className="row">
          <button
            className="primary"
            disabled={running}
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

function JobPanel({ job, onCancel }: { job: Job; onCancel: () => void }) {
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
      {job.status === "done" && result && (
        <p className="small">
          {result.pages} pages, {result.lines} lines, {result.samples} letters
          {"groups" in result && `, ${result.groups} groups, ${result.unsure} unsure`}
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
