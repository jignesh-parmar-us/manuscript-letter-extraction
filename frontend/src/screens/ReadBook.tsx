// Read Book (C16a): the whole book to read into text, as a PDF or a folder of images. Its pages are
// cut into lines and letters like the training pages, but never grouped or reviewed: conversion (C16b)
// reads them. Cutting runs in the background a few pages at a time, so a cancelled or interrupted
// capture keeps the pages already cut and the next one continues where it stopped.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, AppInfo, Book, Job, PageInfo, PageProblem } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";

const READ_JOBS: Job["kind"][] = ["capture_read", "import_pdf", "recut_page"];

interface Props {
  book: Book;
  info: AppInfo | null;
  onChanged: () => void;
}

export default function ReadBook({ book, info, onChanged }: Props) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [problems, setProblems] = useState<PageProblem[]>([]);
  const [pdf, setPdf] = useState("");
  const [folder, setFolder] = useState(book.read_dir);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();

  const load = useCallback(() => {
    api.pages(book.id, "read").then(setPages, setError);
    api.pageProblems(book.id, "read").then(setProblems, setError);
  }, [book.id]);
  useEffect(load, [load, book.read_dir, book.read_pdf]);

  const onEnd = useCallback(() => {
    load();
    onChanged();
  }, [load, onChanged]);
  const [job, setJob] = useJob(book.job && READ_JOBS.includes(book.job.kind) ? book.job : null, onEnd);
  const running = job?.status === "running";
  const notCut = problems.filter((p) => p.problem === "new").length;
  const hasSource = Boolean(book.read_pdf || book.read_dir);

  /** Run a call; when the book already has Read Book pages, ask first, then repeat with force. */
  async function replacing<T>(run: (force: boolean) => Promise<T>): Promise<T | null> {
    setError(null);
    try {
      return await run(false);
    } catch (e) {
      if (e instanceof ApiError && e.needsConfirmation) {
        if (await confirm(`${e.message} Replace them?`, "Replace")) {
          try {
            return await run(true);
          } catch (e2) {
            setError(e2);
          }
        }
      } else setError(e);
      return null;
    }
  }

  async function usePdf() {
    const j = await replacing((force) => api.readPdf(book.id, pdf.trim(), force));
    if (j) setJob(j);
  }
  async function useFolder() {
    if (await replacing((force) => api.readFolder(book.id, folder.trim(), force))) onEnd();
  }
  async function pickFolder() {
    try {
      const r = await api.pickFolder();
      if (r.path) setFolder(r.path);
    } catch (e) {
      setError(e);
    }
  }
  async function recut(pageId: number) {
    const j = await replacing((force) => api.recutPage(book.id, pageId, force));
    if (j) setJob(j);
  }
  async function capture() {
    setError(null);
    try {
      setJob(await api.readCapture(book.id));
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="read-book">
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="card">
        <h2>Read Book</h2>
        <p className="small muted">
          The whole book to read into text. Its pages are cut into letters like the training pages, but never grouped or
          reviewed: the text comes from your labelled letters and readers. A page that reads badly can be used for
          training from the Pages section.
        </p>
        <p className="small">
          Pages:{" "}
          {book.read_pdf ? (
            <>
              <strong>{book.read_pdf}</strong> <span className="muted">(PDF, its pages kept as images in the book folder)</span>
            </>
          ) : book.read_dir ? (
            <code>{book.read_dir}</code>
          ) : (
            <span className="muted">none yet: choose a PDF or a folder of images below.</span>
          )}
        </p>
        <div className="read-source">
          <label className="small">
            PDF file
            <span className="row">
              <input
                aria-label="PDF file"
                placeholder="/path/to/book.pdf"
                value={pdf}
                onChange={(e) => setPdf(e.target.value)}
              />
              <button disabled={running || !pdf.trim()} onClick={usePdf}>
                Use this PDF
              </button>
            </span>
          </label>
          <label className="small">
            or a folder of page images
            <span className="row">
              <input
                aria-label="Folder of page images"
                placeholder="/path/to/the/page/images"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
              />
              {info?.can_pick_folder && (
                <button disabled={running} onClick={pickFolder}>
                  Choose…
                </button>
              )}
              <button disabled={running || !folder.trim() || folder.trim() === book.read_dir} onClick={useFolder}>
                Use this folder
              </button>
            </span>
          </label>
        </div>
        <div className="row">
          <button className="primary" disabled={running || !hasSource || notCut === 0} onClick={capture}>
            {pages.length ? "Cut the remaining pages" : "Cut the pages"}
            {notCut > 0 && ` (${notCut})`}
          </button>
          <span className="small muted">
            {pages.length} of {pages.length + notCut} pages cut
          </span>
        </div>
      </div>

      {job && (
        <>
          <JobPanel job={job} onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />
          {job.kind === "capture_read" && job.status === "cancelled" && (
            <p className="small muted">Stopped: the pages already cut are kept, and the next capture continues from there.</p>
          )}
        </>
      )}

      {pages.length > 0 && (
        <table className="list" aria-label="Read Book pages">
          <thead>
            <tr>
              <th className="num">#</th>
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
                <td className="num">{p.number}</td>
                <td>{p.file}</td>
                <td>
                  <span className={p.status === "OK" ? "badge ok" : "badge warn"}>{p.status}</span>{" "}
                  <span className="muted small">{p.message}</span>
                </td>
                <td className="num">{p.lines}</td>
                <td className="num">{p.samples}</td>
                <td className="actions">
                  <button onClick={() => go(`/books/${book.id}/readpages/${p.id}`)}>Open</button>
                  <button disabled={running} onClick={() => recut(p.id)} title="Cut this page again, for example after a failure">
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
