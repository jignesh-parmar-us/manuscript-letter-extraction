// Read Book → Text → Whole lines: each line image read by Tesseract as it is, without cutting letters
// (measured best on the hand-checked lines: 5.1% of the characters wrong; 4.5% with the language model).
// The page and its text side by side or one above the other; clicking a line shows it on the page and
// clicking an akshara shows what Tesseract and the language model read. "With the language model" shows
// the corrected reading (changed aksharas underlined); downloads follow the choice.
import { useCallback, useEffect, useState } from "react";
import { api, Book, Marker, PageInfo, TextSource, WholeAkshara, WholeLines } from "../api";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";

type Layout = "side" | "stacked";
type Script = "gujarati" | "devanagari";
const FONT = `"Noto Sans Gujarati", "Gujarati Sangam MN", "Shruti", "Noto Sans Devanagari", sans-serif`;

interface Props {
  book: Book;
  pageId: number | null;
  onChanged: () => void;
}

function aksharaText(x: WholeAkshara, script: Script, lm: boolean): string {
  if (lm && x.lm_dev) return script === "gujarati" ? x.lm_guj ?? "" : x.lm_dev;
  return script === "gujarati" ? x.text_guj : x.text_dev;
}

/** A page's lines as plain text (no markers), for the picture and the PDF. */
export function wholePlainLines(t: WholeLines, script: Script, lm: boolean): string[] {
  return t.lines.map((ln) => ln.aksharas.map((x) => (x.space ? " " : "") + aksharaText(x, script, lm)).join(""));
}

function storedLm(): boolean {
  try {
    return localStorage.getItem("whole-lines-lm") !== "off";
  } catch {
    return true;
  }
}

export default function WholeLinesView({ book, pageId, onChanged }: Props) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [read, setRead] = useState<Map<number, number>>(new Map()); // page id -> lines read
  const [text, setText] = useState<WholeLines | null>(null);
  const [layout, setLayout] = useState<Layout>("side");
  const [script, setScript] = useState<Script>("gujarati");
  const [marker, setMarker] = useState<Marker>("none");
  const [lm, setLm] = useState(storedLm);
  const [line, setLine] = useState<number | null>(null); // a line id
  const [picked, setPicked] = useState<WholeAkshara | null>(null);
  const [printing, setPrinting] = useState<WholeLines[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.pages(book.id, "read").then(setPages, setError);
    api.bookWholeLines(book.id).then((ps) => setRead(new Map(ps.map((p) => [p.page_id, p.lines]))), setError);
  }, [book.id, version]);
  useEffect(() => {
    if (pageId === null && pages.length) go(`/books/${book.id}/text/${pages[0].id}`);
  }, [pageId, pages, book.id]);
  const isRead = pageId !== null && read.has(pageId);
  useEffect(() => {
    setText(null);
    setLine(null);
    setPicked(null);
    if (pageId === null || !isRead) return;
    api.wholeLines(pageId).then(setText, setError);
  }, [pageId, isRead, version]);

  const onEnd = useCallback(() => {
    setVersion((v) => v + 1);
    onChanged();
  }, [onChanged]);
  const [job, setJob] = useJob(book.job?.kind === "convert" ? book.job : null, onEnd);
  const running = job?.status === "running";

  async function readPages(ids?: number[]) {
    setError(null);
    try {
      setJob(await api.convert(book.id, ids, "lines"));
    } catch (e) {
      setError(e);
    }
  }
  function chooseLm(on: boolean) {
    setLm(on);
    try {
      localStorage.setItem("whole-lines-lm", on ? "on" : "off");
    } catch {
      // a private window: the choice lasts until the page is closed
    }
  }

  const at = pages.findIndex((p) => p.id === pageId);
  const page = at >= 0 ? pages[at] : null;
  const prev = at > 0 ? pages[at - 1] : undefined;
  const next = at >= 0 && at < pages.length - 1 ? pages[at + 1] : undefined;
  const nRead = pages.filter((p) => read.has(p.id)).length;
  const source: TextSource = lm ? "lines_lm" : "lines";
  const changed = text ? text.lines.reduce((n, ln) => n + ln.aksharas.filter((x) => x.lm_dev).length, 0) : 0;
  const selLine = text?.lines.find((l) => l.line_id === line) ?? null;

  function downloadPicture() {
    if (!text || !page) return;
    const lines = wholePlainLines(text, script, lm);
    const size = 30;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.font = `${size}px ${FONT}`;
    canvas.width = Math.ceil(Math.max(200, ...lines.map((l) => ctx.measureText(l).width))) + 2 * size;
    canvas.height = lines.length * size * 1.7 + size;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#111";
    ctx.font = `${size}px ${FONT}`;
    ctx.textBaseline = "top";
    lines.forEach((l, i) => ctx.fillText(l, size, size / 2 + i * size * 1.7));
    canvas.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${page.file.replace(/\.[^.]+$/, "")}.png`;
      a.click();
      URL.revokeObjectURL(a.href);
    }, "image/png");
  }
  async function printPdf(whole: boolean) {
    try {
      const ids = whole ? pages.filter((p) => read.has(p.id)).map((p) => p.id) : pageId ? [pageId] : [];
      setPrinting(await Promise.all(ids.map((id) => api.wholeLines(id))));
    } catch (e) {
      setError(e);
    }
  }
  useEffect(() => {
    if (!printing) return;
    const done = () => setPrinting(null);
    window.addEventListener("afterprint", done, { once: true });
    window.setTimeout(() => window.print(), 50);
    return () => window.removeEventListener("afterprint", done);
  }, [printing]);

  return (
    <div className={`text-view ${layout}`}>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="row text-tools">
        <button disabled={!prev} onClick={() => prev && go(`/books/${book.id}/text/${prev.id}`)} aria-label="Previous page">
          ◀
        </button>
        <select aria-label="Choose a page" value={pageId ?? ""} onChange={(e) => go(`/books/${book.id}/text/${e.target.value}`)}
          disabled={!pages.length}>
          {pages.map((p, i) => (
            <option key={p.id} value={p.id}>
              {p.file} ({i + 1} of {pages.length}){read.has(p.id) ? " ✓" : ""}
            </option>
          ))}
        </select>
        <button disabled={!next} onClick={() => next && go(`/books/${book.id}/text/${next.id}`)} aria-label="Next page">
          ▶
        </button>
        <button disabled={running || !page} onClick={() => page && readPages([page.id])}>
          {isRead ? "Read this page again" : "Read this page"}
        </button>
        <button disabled={running || !pages.length} onClick={() => readPages()}>
          Read all pages
        </button>
        <span className="small muted">
          {nRead} of {pages.length} read
        </span>
        <span className="spacer" />
        <label className="row small" title="Tesseract's reading corrected by the book's language model (Read Book → Dictionary)">
          <input type="checkbox" checked={lm} onChange={(e) => chooseLm(e.target.checked)} />
          With the language model
        </label>
        <div className="row" role="group" aria-label="Layout">
          <button className={layout === "side" ? "tab active" : "tab"} onClick={() => setLayout("side")}>
            Side by side
          </button>
          <button className={layout === "stacked" ? "tab active" : "tab"} onClick={() => setLayout("stacked")}>
            One above the other
          </button>
        </div>
        <div className="row" role="group" aria-label="Script">
          <button className={script === "gujarati" ? "tab active" : "tab"} onClick={() => setScript("gujarati")}>
            ગુજરાતી
          </button>
          <button className={script === "devanagari" ? "tab active" : "tab"} onClick={() => setScript("devanagari")}>
            देवनागरी
          </button>
        </div>
      </div>
      {job && <JobPanel job={job} onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}
      {!pages.length ? (
        <p className="muted">No Read Book pages are cut yet: upload the book and cut its pages first (Upload &amp; capture).</p>
      ) : (
        <>
          <div className="row text-downloads" aria-label="Download">
            <span className="small muted">Download:</span>
            <select className="narrow small" aria-label="Uncertain letters in downloads" value={marker}
              onChange={(e) => setMarker(e.target.value as Marker)}>
              <option value="none">as read, no marks</option>
              <option value="mark">uncertain as [?]</option>
              <option value="guess">uncertain as [?ક] (best guess)</option>
            </select>
            <a className={`button small${text ? "" : " disabled"}`}
              href={text && pageId ? api.textUrl(book.id, "txt", script, marker, source, pageId) : undefined}>
              Page .txt
            </a>
            <a className={`button small${text ? "" : " disabled"}`}
              href={text && pageId ? api.textUrl(book.id, "docx", script, marker, source, pageId) : undefined}>
              Page Word
            </a>
            <button className="small" disabled={!text} onClick={() => printPdf(false)}>
              Page PDF
            </button>
            <button className="small" disabled={!text} onClick={downloadPicture}>
              Page picture
            </button>
            <span className="small muted">Whole book ({nRead} pages):</span>
            <a className={`button small${nRead ? "" : " disabled"}`}
              href={nRead ? api.textUrl(book.id, "txt", script, marker, source) : undefined}>
              .txt
            </a>
            <a className={`button small${nRead ? "" : " disabled"}`}
              href={nRead ? api.textUrl(book.id, "docx", script, marker, source) : undefined}>
              Word
            </a>
            <button className="small" disabled={!nRead} onClick={() => printPdf(true)}>
              PDF
            </button>
          </div>
          <div className="text-panes">
            <div className="text-page" aria-label="Page">
              {page && (
                <div className="text-page-image" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
                  <img src={page.image} alt={page.file} />
                  {selLine && (
                    <span
                      className="text-box selected"
                      style={{
                        left: `${(100 * selLine.box[0]) / page.width}%`,
                        top: `${(100 * selLine.box[1]) / page.height}%`,
                        width: `${(100 * selLine.box[2]) / page.width}%`,
                        height: `${(100 * selLine.box[3]) / page.height}%`,
                      }}
                    />
                  )}
                </div>
              )}
            </div>
            <div className="text-text" aria-label="Text">
              {!text ? (
                <p className="muted">
                  {isRead ? "Loading…" : "This page is not read yet: Read this page (Tesseract reads each line whole, no letters are cut)."}
                </p>
              ) : (
                <>
                  <p className="small muted">
                    Tesseract read each line whole · {text.uncertain} uncertain aksharas (highlighted)
                    {lm && ` · ${changed} changed by the language model (underlined)`}
                  </p>
                  <div className={`text-lines ${script}`} lang={script === "gujarati" ? "gu" : "sa"}>
                    {text.lines.map((ln) => (
                      <div key={ln.line_id} className={`text-line whole${ln.line_id === line ? " selected" : ""}`}
                        onClick={() => setLine(ln.line_id)}>
                        {ln.aksharas.map((x, i) => (
                          <span key={i}>
                            {x.space && " "}
                            <span
                              className={`text-letter${x.uncertain ? " uncertain" : ""}${lm && x.lm_dev ? " lm" : ""}${picked === x ? " selected" : ""}`}
                              onClick={() => setPicked(x)}
                            >
                              {aksharaText(x, script, lm)}
                            </span>
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                  {picked && (
                    <p className="small text-letter-info" aria-live="polite">
                      <strong>{aksharaText(picked, script, lm)}</strong> · Tesseract: {script === "gujarati" ? picked.text_guj : picked.text_dev} (
                      {Math.round(picked.conf)}){picked.lm_dev && ` · the language model: ${script === "gujarati" ? picked.lm_guj : picked.lm_dev}`}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
      {printing && (
        <div className="print-text" lang="gu">
          {printing.map((t) => (
            <section key={t.page_id}>
              {printing.length > 1 && <h3>{pages.find((p) => p.id === t.page_id)?.file}</h3>}
              {wholePlainLines(t, script, lm).map((l, i) => (
                <p key={i}>{l}</p>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
