// Read Book → Text → Whole lines: each line image read by Tesseract as it is, without cutting letters
// (measured best on the hand-checked lines: 5.1% of the characters wrong; 4.5% with the language model).
//
// Two layouts: "Whole page" (the page above its text) and "Line by line" (one line cropped from the page,
// its text and its correction below, ◀ ▶ between lines). Clicking an akshara shows it on the page; the arrow
// keys move between aksharas (← →) and lines (↑ ↓). A line can be corrected (✎, or the box in Line by line)
// and marked reviewed (✓): a reviewed line is also kept as a checked line (Line truth). "With the language
// model" shows the corrected reading (changed aksharas underlined); downloads follow it and the corrections.
//
// engine "search" (Whole lines (our reader)): the same view with the line search's reading (linesearch.py):
// no Tesseract, its aksharas with their places; where Tesseract reads differently is highlighted. Its reader
// is trained on the book's reviewed letters (Retrain when they changed), and Measure scores it fold-fair on
// the checked lines. Corrections and ✓ are the line's: the same in both views.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Book, LineEngine, LineSearchState, Marker, PageInfo, TextSource, WholeAkshara, WholeLine, WholeLines } from "../api";
import ErrorBox from "../components/ErrorBox";
import LetterPalette from "../components/LetterPalette";
import { PageImagesPdf, PrintPages } from "../components/PageDownloads";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";
import LineCrop, { AlignedText, Strip } from "./LineCrop";
import type { Layout, PageStyle } from "./TextView";

type Script = "gujarati" | "devanagari";
const FONT = `"Noto Sans Gujarati", "Gujarati Sangam MN", "Shruti", "Noto Sans Devanagari", sans-serif`;

interface Props {
  book: Book;
  pageId: number | null;
  onChanged: () => void;
  engine?: LineEngine;
  layout: Layout;
  pageStyle: PageStyle;
  aligned: boolean;
}

function aksharaText(x: WholeAkshara, script: Script, lm: boolean): string {
  if (lm && x.lm_dev) return script === "gujarati" ? x.lm_guj ?? "" : x.lm_dev;
  return script === "gujarati" ? x.text_guj : x.text_dev;
}

/** A line as shown: your correction, or the reading (with or without the language model). */
function lineText(ln: WholeLine, script: Script, lm: boolean): string {
  if (ln.edited_dev) return script === "gujarati" ? ln.edited_guj ?? "" : ln.edited_dev;
  return ln.aksharas.map((x) => (x.space ? " " : "") + aksharaText(x, script, lm)).join("");
}

/** The line image to show for a line (only its own ink), when the server gave one. */
function stripOf(ln: WholeLine): Strip | undefined {
  return ln.image && ln.image_box ? { src: ln.image, box: ln.image_box } : undefined;
}

/** A page's lines as plain text (no markers), for the picture and the PDF. */
export function wholePlainLines(t: WholeLines, script: Script, lm: boolean): string[] {
  return t.lines.map((ln) => lineText(ln, script, lm));
}

function storedLm(): boolean {
  try {
    return localStorage.getItem("whole-lines-lm") !== "off";
  } catch {
    return true;
  }
}

/** Arrow keys outside text boxes: ← → by `step` letters, ↑ ↓ by `line` lines. */
export function useArrowKeys(onMove: (step: number, line: number) => void) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const move = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key];
      if (!move) return;
      e.preventDefault();
      onMove(move[0], move[1]);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onMove]);
}

export default function WholeLinesView({ book, pageId, onChanged, engine = "tesseract", layout, pageStyle, aligned }: Props) {
  const ours = engine === "search";
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [read, setRead] = useState<Map<number, number>>(new Map()); // page id -> lines read (by this engine)
  const [state, setState] = useState<LineSearchState | null>(null); // our reader: training and measure
  const [text, setText] = useState<WholeLines | null>(null);
  const [script, setScript] = useState<Script>("gujarati");
  const [marker, setMarker] = useState<Marker>("none");
  const [lmChoice, setLm] = useState(storedLm);
  const lm = lmChoice && !ours; // our reader uses the language model in its search already
  const [li, setLi] = useState(0); // the current line
  const [ai, setAi] = useState<number | null>(null); // the selected akshara of that line
  const [editing, setEditing] = useState<number | null>(null); // a line id (Whole page)
  const [draft, setDraft] = useState("");
  const [letters, setLetters] = useState(false);
  const [busy, setBusy] = useState(false);
  const [printing, setPrinting] = useState<WholeLines[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.pages(book.id, "read").then(setPages, setError);
    api.bookWholeLines(book.id, engine).then((ps) => setRead(new Map(ps.map((p) => [p.page_id, p.lines]))), setError);
    if (ours) {
      api.lineSearchReader(book.id).then(setState, setError);
    }
  }, [book.id, version, engine, ours]);
  useEffect(() => {
    if (pageId === null && pages.length) go(`/books/${book.id}/text/${pages[0].id}`);
  }, [pageId, pages, book.id]);
  const isRead = pageId !== null && read.has(pageId);
  useEffect(() => {
    setText(null);
    setAi(null);
    setEditing(null);
    if (pageId === null || !isRead) return;
    api.wholeLines(pageId, engine).then(setText, setError);
  }, [pageId, isRead, version, engine]);
  useEffect(() => setLi(0), [pageId]);

  const onEnd = useCallback(() => {
    setVersion((v) => v + 1);
    onChanged();
  }, [onChanged]);
  const kinds = ours ? ["line_search", "line_search_train", "line_search_measure"] : ["convert"];
  const [job, setJob] = useJob(book.job && kinds.includes(book.job.kind) ? book.job : null, onEnd);
  const running = job?.status === "running";

  async function readPages(ids?: number[]) {
    setError(null);
    try {
      setJob(await api.convert(book.id, ids, "lines"));
    } catch (e) {
      setError(e);
    }
  }
  async function readOurs(ids?: number[]) {
    setError(null);
    try {
      setJob(await api.lineSearch(book.id, ids));
    } catch (e) {
      setError(e);
    }
  }
  async function retrain() {
    setError(null);
    try {
      setJob(await api.lineSearchTrain(book.id));
    } catch (e) {
      setError(e);
    }
  }
  async function measure() {
    setError(null);
    try {
      setJob(await api.lineSearchMeasure(book.id));
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
  const unread = pages.filter((p) => !read.has(p.id)).map((p) => p.id);
  const source: TextSource = ours ? "search" : lm ? "lines_lm" : "lines";
  const reader = state?.reader ?? null;
  const lines = text?.lines ?? [];
  const cur = lines[Math.min(li, Math.max(0, lines.length - 1))] ?? null;
  const picked = cur && ai !== null && !cur.edited_dev ? cur.aksharas[ai] ?? null : null;
  const changed = lines.reduce((n, ln) => n + ln.aksharas.filter((x) => x.lm_dev).length, 0);
  const searched = lines.filter((ln) => ln.searched).length;
  const reviewed = lines.filter((ln) => ln.reviewed).length;

  // the line's text in the correction box (Line by line) follows the current line
  useEffect(() => {
    if (cur) setDraft(lineText(cur, script, lm));
    setLetters(false);
  }, [cur?.line_id, cur?.edited_dev, script, lm]); // eslint-disable-line react-hooks/exhaustive-deps

  // ← → between aksharas (and on to the next line), ↑ ↓ between lines
  const onMove = useCallback(
    (step: number, line: number) => {
      if (!lines.length) return;
      if (line) {
        setLi((i) => Math.max(0, Math.min(lines.length - 1, i + line)));
        setAi(0);
        return;
      }
      const n = cur && !cur.edited_dev ? cur.aksharas.length : 0;
      const nextAi = (ai ?? (step > 0 ? -1 : n)) + step;
      if (nextAi >= 0 && nextAi < n) setAi(nextAi);
      else if (nextAi >= n && li < lines.length - 1) {
        setLi(li + 1);
        setAi(0);
      } else if (nextAi < 0 && li > 0) {
        const p = lines[li - 1];
        setLi(li - 1);
        setAi(p.edited_dev ? null : p.aksharas.length - 1);
      }
    },
    [lines, cur, ai, li],
  );
  useArrowKeys(onMove);

  async function saveLine(ln: WholeLine, change: { text?: string; reviewed?: boolean }) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.saveWholeLine(ln.line_id, { ...change, shown: lineText(ln, "devanagari", lm) });
      setText((t) => t && { ...t, lines: t.lines.map((l) => (l.line_id === ln.line_id ? { ...l, ...r } : l)) });
      setEditing(null);
      return true;
    } catch (e) {
      setError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** Put `s` in place of the selection of the correction box and keep the cursor after it. */
  function insert(s: string) {
    const el = input.current;
    const a = el?.selectionStart ?? draft.length;
    const b = el?.selectionEnd ?? draft.length;
    setDraft(draft.slice(0, a) + s + draft.slice(b));
    window.setTimeout(() => {
      el?.focus();
      el?.setSelectionRange(a + s.length, a + s.length);
    }, 0);
  }
  function backspace() {
    const el = input.current;
    const a = el?.selectionStart ?? draft.length;
    const b = el?.selectionEnd ?? draft.length;
    const from = a < b ? a : a - (Array.from(draft.slice(0, a)).pop()?.length ?? 0);
    setDraft(draft.slice(0, from) + draft.slice(b));
    window.setTimeout(() => {
      el?.focus();
      el?.setSelectionRange(from, from);
    }, 0);
  }

  function downloadPicture() {
    if (!text || !page) return;
    const plain = wholePlainLines(text, script, lm);
    const size = 30;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.font = `${size}px ${FONT}`;
    canvas.width = Math.ceil(Math.max(200, ...plain.map((l) => ctx.measureText(l).width))) + 2 * size;
    canvas.height = plain.length * size * 1.7 + size;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#111";
    ctx.font = `${size}px ${FONT}`;
    ctx.textBaseline = "top";
    plain.forEach((l, i) => ctx.fillText(l, size, size / 2 + i * size * 1.7));
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
      setPrinting(await Promise.all(ids.map((id) => api.wholeLines(id, engine))));   // the reading of this tab
    } catch (e) {
      setError(e);
    }
  }

  /** One line's aksharas, clickable (or its correction, as plain text). */
  function lineSpans(ln: WholeLine, i: number) {
    if (ln.edited_dev)
      return (
        <span className="edited" title="Your correction">
          {script === "gujarati" ? ln.edited_guj : ln.edited_dev}
        </span>
      );
    return ln.aksharas.map((x, k) => (
      <span key={k}>
        {x.space && " "}
        <span
          className={`text-letter${x.uncertain ? " uncertain" : ""}${lm && x.lm_dev ? " lm" : ""}${i === li && k === ai ? " selected" : ""}`}
          onClick={(e) => {
            e.stopPropagation();
            setLi(i);
            setAi(k);
          }}
        >
          {aksharaText(x, script, lm)}
        </span>
      </span>
    ));
  }

  function reviewButton(ln: WholeLine, i: number) {
    return (
      <button
        className={`proofread-mark${ln.reviewed ? " done" : ""}`}
        disabled={busy}
        aria-label={`Line ${i + 1} ${ln.reviewed ? "reviewed" : "not reviewed"}`}
        title={ln.reviewed ? "Reviewed (also a checked line in Line truth): click to undo" : "Mark this line reviewed: its text is right"}
        onClick={(e) => {
          e.stopPropagation();
          saveLine(ln, { reviewed: !ln.reviewed });
        }}
      >
        ✓
      </button>
    );
  }

  /** A line's text under its strip: each akshara under its letter, or plain text for a corrected line. */
  function lineTextRow(ln: WholeLine, i: number) {
    if (!aligned && layout === "line") return null;            // Line by line: the correction box holds the text
    if (aligned && page && !ln.edited_dev && ln.aksharas.length > 0 && ln.aksharas.every((x) => x.box))
      return (
        <AlignedText
          page={page}
          box={ln.box}
          strip={stripOf(ln)}
          items={ln.aksharas.map((x, k) => ({
            key: k,
            box: x.box!,
            text: aksharaText(x, script, lm),
            className: `${x.uncertain ? "uncertain " : ""}${lm && x.lm_dev ? "lm " : ""}${i === li && k === ai ? "selected" : ""}`.trim(),
            onClick: () => {
              setLi(i);
              setAi(k);
            },
          }))}
        />
      );
    return (
      <div className={`text-lines ${script}`} lang={script === "gujarati" ? "gu" : "sa"}>
        <div className={`text-line${ln.reviewed ? " reviewed" : ""}`}>{lineSpans(ln, i)}</div>
      </div>
    );
  }

  // the current line in view when moving with the keys
  const lineRefs = useRef(new Map<number, HTMLElement>());
  useEffect(() => {
    if (layout === "page") lineRefs.current.get(li)?.scrollIntoView?.({ block: "nearest" });
  }, [li, layout]);

  // the Letters palette under the correction box, in the page's flow: it never covers the box and has no
  // scroll of its own (As a page: below the panes, since the text pane scrolls)
  const paletteRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (letters) paletteRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [letters]);
  const palette = letters && (
    <div ref={paletteRef} className="line-palette">
      <LetterPalette onKey={insert} onBackspace={backspace} closable onClose={() => setLetters(false)}
        extra={<button onClick={() => insert(" ")}>Space</button>} />
    </div>
  );

  const correctionBox = (ln: WholeLine, onCancel?: () => void) => (
    <>
      <div className="line-edit">
        <input
          ref={input}
          aria-label="Correct the line"
          lang="gu"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") saveLine(ln, { text: draft });
            if (e.key === "Escape") onCancel?.();
          }}
        />
        <button className="primary" disabled={busy} onClick={() => saveLine(ln, { text: draft })}>
          Save
        </button>
        {ln.edited_dev && (
          <button className="link" disabled={busy} onClick={() => saveLine(ln, { text: "" })}
            title="Remove your correction: show what was read">
            Use the reading
          </button>
        )}
        <button className="link" onClick={() => setLetters((v) => !v)}>
          {letters ? "Hide letters" : "Letters…"}
        </button>
        {onCancel && (
          <button className="link" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {layout !== "page" || pageStyle !== "image" ? palette : null}
    </>
  );

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
        {ours ? (
          <>
            <button disabled={running || !page} onClick={() => page && readOurs([page.id])}
              title="Our reader reads this page's lines (no Tesseract needed; the page must be cut into lines and letters)">
              {isRead ? "Read this page again" : "Read this page"}
            </button>
            <button disabled={running || !pages.length} onClick={() => readOurs()}
              title="Our reader reads every page of this part (about 7 s per line). The first time, it learns the letters first (a few minutes).">
              Read all pages
            </button>
            <button disabled={running || !unread.length} onClick={() => readOurs(unread)}
              title="Our reader reads only the pages it has not read yet (about 7 s per line)">
              Read unread pages ({unread.length})
            </button>
          </>
        ) : (
          <>
            <button disabled={running || !page} onClick={() => page && readPages([page.id])}>
              {isRead ? "Read this page again" : "Read this page"}
            </button>
            <button disabled={running || !pages.length} onClick={() => readPages()}>
              Read all pages
            </button>
            <button disabled={running || !unread.length} onClick={() => readPages(unread)}
              title="Read only the pages that are not read yet">
              Read unread pages ({unread.length})
            </button>
          </>
        )}
        <span className="small muted">
          {nRead} of {pages.length} read
        </span>
        <span className="spacer" />
        {!ours && (
          <label className="row small" title="Tesseract's reading corrected by the book's language model (Read Book → Dictionary)">
            <input type="checkbox" checked={lm} onChange={(e) => chooseLm(e.target.checked)} />
            With the language model
          </label>
        )}
        <div className="row" role="group" aria-label="Script">
          <button className={script === "gujarati" ? "tab active" : "tab"} onClick={() => setScript("gujarati")}>
            ગુજરાતી
          </button>
          <button className={script === "devanagari" ? "tab active" : "tab"} onClick={() => setScript("devanagari")}>
            देवनागरी
          </button>
        </div>
      </div>
      {ours && (
        <div className="row our-reader small" aria-label="Our reader">
          <span>
            {reader
              ? `Reader trained on ${reader.letters} reviewed letters and ${reader.lines} checked lines (${reader.labels} labels), ${new Date(reader.trained_at).toLocaleString()}.`
              : "No reader yet: Retrain (or Read all pages) learns the letters first."}
            {reader?.changed && <strong> Your reviewed letters or checked lines changed since: retrain to use them.</strong>}
          </span>
          <button className={!reader || reader.changed ? "primary" : ""} disabled={running}
            onClick={retrain}
            title="Learn again from the reviewed groups and every checked line (✓ or Line truth), as they are now (about half an hour). It does not read the pages: Read all pages (or a page) afterwards to use it.">
            Retrain
          </button>
          <button disabled={running} onClick={measure}
            title="Score our reader on your checked lines (✓ or Line truth). Fair: for each group of pages it is trained again without them, since they are also Training Data pages (about 30 minutes per group, four groups: about 2 hours).">
            Measure
          </button>
        </div>
      )}
      {ours && state?.measure && <MeasureResult m={state.measure} />}
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
            <PageImagesPdf bookId={book.id} pageId={page?.id ?? null} nPages={pages.length} />
          </div>
          {!text ? (
            <p className="muted">
              {isRead
                ? "Loading…"
                : ours
                  ? "Our reader has not read this page yet: Read this page."
                  : "This page is not read yet: Read this page (Tesseract reads each line whole, no letters are cut)."}
            </p>
          ) : (
            <>
              <p className="small muted">
                {ours
                  ? `Our reader read ${searched} of ${lines.length} lines, without Tesseract · ${text.uncertain} aksharas where Tesseract reads differently (highlighted)`
                  : `Tesseract read each line whole · ${text.uncertain} uncertain aksharas (highlighted)`}
                {!ours && searched > 0 && ` · our reader's second opinion on ${searched} of ${lines.length} lines`}
                {lm && ` · ${changed} changed by the language model (underlined)`} · {reviewed} of {lines.length} lines reviewed ·
                ← → aksharas, ↑ ↓ lines
              </p>
              {layout === "line" && cur && page ? (
                <div className="line-by-line" aria-label="Line by line">
                  <div className="row line-nav">
                    <button disabled={li === 0} onClick={() => { setLi(li - 1); setAi(null); }} aria-label="Previous line">
                      ◀ Previous line
                    </button>
                    <span className="small muted">
                      Line {li + 1} of {lines.length}
                    </span>
                    <button disabled={li >= lines.length - 1} onClick={() => { setLi(li + 1); setAi(null); }} aria-label="Next line">
                      Next line ▶
                    </button>
                    {reviewButton(cur, li)}
                    <span className="small muted">{cur.reviewed ? "reviewed" : "not reviewed"}</span>
                  </div>
                  <LineCrop
                    page={page}
                    box={cur.box}
                    strip={stripOf(cur)}
                    marks={cur.edited_dev ? [] : cur.aksharas.flatMap((x, k) =>
                      x.box && (x.uncertain || k === ai)
                        ? [{ key: k, box: x.box, className: `${x.uncertain ? "uncertain " : ""}${k === ai ? "selected" : ""}`.trim(),
                            onClick: () => setAi(k) }]
                        : [])}
                  />
                  {lineTextRow(cur, li)}
                  {correctionBox(cur)}
                </div>
              ) : (
                pageStyle === "image" ? (
                  <>
                  <div className="text-panes">
                    <div className="text-page" aria-label="Page">
                      {page && (
                        <div className="text-page-image" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
                          <img src={page.image} alt={page.file} />
                          {cur && (
                            <span className="text-box line-mark" style={{
                              left: `${(100 * cur.box[0]) / page.width}%`, top: `${(100 * cur.box[1]) / page.height}%`,
                              width: `${(100 * cur.box[2]) / page.width}%`, height: `${(100 * cur.box[3]) / page.height}%` }} />
                          )}
                          {picked?.box && (
                            <span className="text-box selected" style={{
                              left: `${(100 * picked.box[0]) / page.width}%`, top: `${(100 * picked.box[1]) / page.height}%`,
                              width: `${(100 * picked.box[2]) / page.width}%`, height: `${(100 * picked.box[3]) / page.height}%` }} />
                          )}
                        </div>
                      )}
                    </div>
                    <div className="text-text" aria-label="Text">
                      <div className={`text-lines ${script}`} lang={script === "gujarati" ? "gu" : "sa"}>
                        {lines.map((ln, i) => (
                          <div key={ln.line_id} ref={(el) => { if (el) lineRefs.current.set(i, el); }}
                            className={`text-line whole${i === li ? " selected" : ""}${ln.reviewed ? " reviewed" : ""}`}
                            onClick={() => setLi(i)}>
                            {editing === ln.line_id ? (
                              correctionBox(ln, () => setEditing(null))
                            ) : (
                              <>
                                {lineSpans(ln, i)}
                                <span className="line-tools">
                                  <button aria-label={`Correct line ${i + 1}`} title="Correct this line" disabled={busy}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setLi(i);
                                      setDraft(lineText(ln, script, lm));
                                      setEditing(ln.line_id);
                                    }}>
                                    ✎
                                  </button>
                                  {reviewButton(ln, i)}
                                </span>
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                  {editing !== null && palette}
                  </>
                ) : (
                <div className="interlinear" aria-label="Lines">
                  {page && lines.map((ln, i) => (
                    <div key={ln.line_id} ref={(el) => { if (el) lineRefs.current.set(i, el); }}
                      className={`interlinear-line${i === li ? " selected" : ""}${ln.reviewed ? " reviewed" : ""}`}
                      onClick={() => setLi(i)}>
                      <LineCrop
                        page={page}
                        box={ln.box}
                        strip={stripOf(ln)}
                        marks={ln.edited_dev ? [] : ln.aksharas.flatMap((x, k) =>
                          x.box && (x.uncertain || (i === li && k === ai))
                            ? [{ key: k, box: x.box, className: `${x.uncertain ? "uncertain " : ""}${i === li && k === ai ? "selected" : ""}`.trim(),
                                onClick: () => { setLi(i); setAi(k); } }]
                            : [])}
                      />
                      {lineTextRow(ln, i)}
                      {editing === ln.line_id ? (
                        correctionBox(ln, () => setEditing(null))
                      ) : (
                        <div className="row line-tools-row">
                          <span className="small muted">Line {i + 1}</span>
                          <button aria-label={`Correct line ${i + 1}`} title="Correct this line" disabled={busy}
                            onClick={(e) => {
                              e.stopPropagation();
                              setLi(i);
                              setDraft(lineText(ln, script, lm));
                              setEditing(ln.line_id);
                            }}>
                            ✎ Correct
                          </button>
                          {reviewButton(ln, i)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                )
              )}
              {picked && ours && (
                <p className="small text-letter-info" aria-live="polite">
                  <strong>{aksharaText(picked, script, lm)}</strong> · our reader
                  {picked.other_dev !== undefined &&
                    ` · Tesseract: ${picked.other_dev ? (script === "gujarati" ? picked.other_guj : picked.other_dev) : "nothing here"}`}
                </p>
              )}
              {picked && !ours && (
                <p className="small text-letter-info" aria-live="polite">
                  <strong>{aksharaText(picked, script, lm)}</strong> · Tesseract: {script === "gujarati" ? picked.text_guj : picked.text_dev} (
                  {Math.round(picked.conf ?? 0)}){picked.lm_dev && ` · the language model: ${script === "gujarati" ? picked.lm_guj : picked.lm_dev}`}
                  {picked.search_dev !== undefined &&
                    ` · our reader: ${picked.search_dev ? (script === "gujarati" ? picked.search_guj : picked.search_dev) : "nothing here"}`}
                </p>
              )}
            </>
          )}
        </>
      )}
      {printing && (
        <PrintPages
          pages={printing.map((t) => ({ key: t.page_id, title: pages.find((p) => p.id === t.page_id)?.file,
            lines: wholePlainLines(t, script, lm) }))}
          onDone={() => setPrinting(null)}
        />
      )}
    </div>
  );
}

/** The last fold-fair measure of our reader on the checked lines, with every line to check by eye. */
function MeasureResult({ m }: { m: NonNullable<LineSearchState["measure"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="measure-result small" aria-label="Measure">
      <p>
        On <strong>{m.lines}</strong> checked lines ({m.pages} pages, {m.chars} characters; measured{" "}
        {new Date(m.measured_at).toLocaleString()}), characters wrong: <strong>our reader {m.cer.ours}%</strong> ·
        Tesseract {m.cer.tesseract}% · Tesseract + language model {m.cer.tesseract_lm}%. As a second opinion it marks{" "}
        {m.marked}% of the aksharas and {m.caught} of the {m.mistakes} still wrong after Tesseract + language model.{" "}
        <button className="link" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide the lines" : "Show the lines"}
        </button>
      </p>
      <p className="muted">
        Fair: our reader and its language model were trained without the pages being scored ({m.folds} groups of
        pages). The language model beside Tesseract knows every page, and checked text typed from Tesseract's
        reading slightly favours Tesseract.
      </p>
      {open && (
        <table className="measure-lines">
          <thead>
            <tr>
              <th>Page · line</th>
              <th>Checked text / our reader / Tesseract</th>
              <th className="num">Ours wrong</th>
              <th className="num">Tesseract wrong</th>
            </tr>
          </thead>
          <tbody>
            {m.line_results.map((x) => (
              <tr key={`${x.page}-${x.line}`}>
                <td>
                  {x.page} · {x.line}
                </td>
                <td lang="sa" className="measure-texts">
                  <div>{x.truth}</div>
                  <div className={x.wrong.ours ? "measure-diff" : ""}>{x.ours}</div>
                  <div className={x.wrong.tesseract ? "measure-diff" : ""}>{x.tesseract}</div>
                </td>
                <td className="num">{x.wrong.ours}</td>
                <td className="num">{x.wrong.tesseract}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
