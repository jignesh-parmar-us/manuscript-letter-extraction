// Read Book → Text (C16b): a page and its converted text, side by side or one above the other.
// Printed books: "Tesseract only" shows what Tesseract read; "Tesseract + your groups" adds the labelled
// groups' second opinion and the uncertain marks it brings (both are stored, so switching is instant).
// Uncertain letters are highlighted in the text and on the page; clicking a letter shows it on the
// page, and clicking a box on the page shows its letter in the text. Convert the page or all pages
// (a background job; each page is kept as soon as it is done). Downloads: .txt and Word from the
// backend; PDF printed by the browser from the text; a picture (.png) of the text drawn by the browser,
// which joins Gujarati letters correctly.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Book, Marker, PageInfo, PageText, Readers, TextLetter } from "../api";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";
import PagePicker from "./PagePicker";

type Layout = "side" | "stacked";
type Script = "gujarati" | "devanagari";
const FONT = `"Noto Sans Gujarati", "Gujarati Sangam MN", "Shruti", "Noto Sans Devanagari", sans-serif`;

interface Props {
  book: Book;
  pageId: number | null;
  onChanged: () => void;
}

/** A letter as one set of readers sees it: its text and whether it is uncertain. */
function view(x: TextLetter, readers: Readers): { dev: string; guj: string; uncertain: boolean; conf: number } {
  if (readers === "tesseract" && x.t_text_dev !== undefined)
    return { dev: x.t_text_dev, guj: x.t_text_guj ?? "", uncertain: !!x.t_uncertain, conf: x.t_conf ?? 0 };
  return { dev: x.text_dev, guj: x.text_guj, uncertain: x.uncertain, conf: x.conf };
}

function shown(x: TextLetter, script: Script, readers: Readers = "both"): string {
  const v = view(x, readers);
  return (script === "gujarati" ? v.guj : v.dev) || "?";
}

/** A page's lines as plain text (the best guesses, no markers), in one script. */
export function plainLines(text: PageText, script: Script, readers: Readers = "both"): string[] {
  return text.lines.map((line) => line.map((x) => (x.space ? " " : "") + shown(x, script, readers)).join(""));
}

function storedReaders(): Readers {
  try {
    return localStorage.getItem("text-readers") === "both" ? "both" : "tesseract";
  } catch {
    return "tesseract";
  }
}

export default function TextView({ book, pageId, onChanged }: Props) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [converted, setConverted] = useState<Map<number, number>>(new Map()); // page id -> uncertain letters
  const [text, setText] = useState<PageText | null>(null);
  const [layout, setLayout] = useState<Layout>("side");
  const [script, setScript] = useState<Script>("gujarati");
  const [marker, setMarker] = useState<Marker>("mark");
  const [readersChoice, setReadersChoice] = useState<Readers>(storedReaders);
  function chooseReaders(r: Readers) {
    setReadersChoice(r);
    try {
      localStorage.setItem("text-readers", r);
    } catch {
      // a private window: the choice lasts until the page is closed
    }
  }
  const [selected, setSelected] = useState<number | null>(null); // a sample id
  const [choosing, setChoosing] = useState(false);
  const [printing, setPrinting] = useState<PageText[] | null>(null); // texts to print as PDF
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    api.pages(book.id, "read").then(setPages, setError);
    api.bookTexts(book.id).then((ts) => setConverted(new Map(ts.map((t) => [t.page_id, t.uncertain]))), setError);
  }, [book.id, version]);
  // no page chosen: open the first one
  useEffect(() => {
    if (pageId === null && pages.length) go(`/books/${book.id}/text/${pages[0].id}`);
  }, [pageId, pages, book.id]);
  useEffect(() => {
    setText(null);
    setSelected(null);
    if (pageId === null || !converted.has(pageId)) return;
    api.pageText(pageId).then(setText, setError);
  }, [pageId, converted]);

  const onEnd = useCallback(() => {
    setVersion((v) => v + 1);
    onChanged();
  }, [onChanged]);
  const [job, setJob] = useJob(book.job?.kind === "convert" ? book.job : null, onEnd);
  const running = job?.status === "running";

  async function convert(pageIds?: number[]) {
    setError(null);
    try {
      setJob(await api.convert(book.id, pageIds));
    } catch (e) {
      setError(e);
    }
  }

  const at = pages.findIndex((p) => p.id === pageId);
  const page = at >= 0 ? pages[at] : null;
  const prev = at > 0 ? pages[at - 1] : undefined;
  const next = at >= 0 && at < pages.length - 1 ? pages[at + 1] : undefined;
  const letters = useMemo(() => (text ? text.lines.flat() : []), [text]);
  const hasTesseract = !!text?.readers.includes("tesseract");
  const readers: Readers = hasTesseract ? readersChoice : "both";
  const uncertainCount = readers === "tesseract" ? text?.uncertain_tesseract ?? 0 : text?.uncertain ?? 0;
  const sel = letters.find((x) => x.sample_id === selected) ?? null;

  // the selected letter in view on the other side
  const boxRefs = useRef(new Map<number, HTMLElement>());
  const letterRefs = useRef(new Map<number, HTMLElement>());
  function pick(id: number, from: "text" | "page") {
    setSelected(id);
    const other = (from === "text" ? boxRefs : letterRefs).current.get(id);
    other?.scrollIntoView?.({ block: "center", inline: "center" });
  }

  function downloadPicture() {
    if (!text || !page) return;
    const lines = plainLines(text, script, readers);
    const size = 30;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.font = `${size}px ${FONT}`;
    const width = Math.ceil(Math.max(200, ...lines.map((l) => ctx.measureText(l).width))) + 2 * size;
    canvas.width = width;
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
      const ids = whole ? pages.filter((p) => converted.has(p.id)).map((p) => p.id) : pageId ? [pageId] : [];
      setPrinting(await Promise.all(ids.map((id) => api.pageText(id))));
    } catch (e) {
      setError(e);
    }
  }
  useEffect(() => {
    if (!printing) return;
    const done = () => setPrinting(null);
    window.addEventListener("afterprint", done, { once: true });
    window.setTimeout(() => window.print(), 50); // after the print view is drawn
    return () => window.removeEventListener("afterprint", done);
  }, [printing]);

  const nConverted = pages.filter((p) => converted.has(p.id)).length;

  return (
    <div className={`text-view ${layout}`}>
      {choosing && (
        <PagePicker
          pages={pages}
          currentId={pageId}
          onPick={(p) => {
            setChoosing(false);
            go(`/books/${book.id}/text/${p.id}`);
          }}
          onClose={() => setChoosing(false)}
        />
      )}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="row text-tools">
        <button disabled={!prev} onClick={() => prev && go(`/books/${book.id}/text/${prev.id}`)} aria-label="Previous page">
          ◀
        </button>
        <button className="page-choose" onClick={() => setChoosing(true)} disabled={!pages.length}>
          {page ? page.file : "Choose a page"}{" "}
          <span className="muted small">{page ? `${at + 1} of ${pages.length}` : `${pages.length} pages`} ▾</span>
        </button>
        <button disabled={!next} onClick={() => next && go(`/books/${book.id}/text/${next.id}`)} aria-label="Next page">
          ▶
        </button>
        <button disabled={running || !page} onClick={() => page && convert([page.id])}>
          {page && converted.has(page.id) ? "Convert this page again" : "Convert this page"}
        </button>
        <button disabled={running || !pages.length} onClick={() => convert()}>
          Convert all pages
        </button>
        <span className="small muted">
          {nConverted} of {pages.length} converted
        </span>
        <span className="spacer" />
        <div className="row" role="group" aria-label="Layout">
          <button className={layout === "side" ? "tab active" : "tab"} onClick={() => setLayout("side")}>
            Side by side
          </button>
          <button className={layout === "stacked" ? "tab active" : "tab"} onClick={() => setLayout("stacked")}>
            One above the other
          </button>
        </div>
        {hasTesseract && (
          <div className="row" role="group" aria-label="Readers">
            <button className={readers === "tesseract" ? "tab active" : "tab"} onClick={() => chooseReaders("tesseract")}
              title="What Tesseract read, as it is">
              Tesseract only
            </button>
            <button className={readers === "both" ? "tab active" : "tab"} onClick={() => chooseReaders("both")}
              title="Tesseract checked against your labelled groups: disagreements are marked uncertain">
              Tesseract + your groups
            </button>
          </div>
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
      {job && <JobPanel job={job} onCancel={() => api.cancelJob(job.id).then(setJob, setError)} />}
      {!pages.length ? (
        <p className="muted">No Read Book pages are cut yet: upload the book and cut its pages first (Upload &amp; capture).</p>
      ) : (
        <>
          <div className="row text-downloads" aria-label="Download">
            <span className="small muted">Download:</span>
            <select className="narrow small" aria-label="Uncertain letters in downloads" value={marker}
              onChange={(e) => setMarker(e.target.value as Marker)} title="How uncertain letters are written in the .txt and Word files">
              <option value="mark">uncertain as [?]</option>
              <option value="guess">uncertain as [?ક] (best guess)</option>
              <option value="none">best guess, no marks</option>
            </select>
            <a className={`button small${text ? "" : " disabled"}`} href={text && pageId ? api.textUrl(book.id, "txt", script, marker, readers, pageId) : undefined}>
              Page .txt
            </a>
            <a className={`button small${text ? "" : " disabled"}`} href={text && pageId ? api.textUrl(book.id, "docx", script, marker, readers, pageId) : undefined}>
              Page Word
            </a>
            <button className="small" disabled={!text} onClick={() => printPdf(false)}>
              Page PDF
            </button>
            <button className="small" disabled={!text} onClick={downloadPicture}>
              Page picture
            </button>
            <span className="small muted">Whole book ({nConverted} pages):</span>
            <a className={`button small${nConverted ? "" : " disabled"}`} href={nConverted ? api.textUrl(book.id, "txt", script, marker, readers) : undefined}>
              .txt
            </a>
            <a className={`button small${nConverted ? "" : " disabled"}`} href={nConverted ? api.textUrl(book.id, "docx", script, marker, readers) : undefined}>
              Word
            </a>
            <button className="small" disabled={!nConverted} onClick={() => printPdf(true)}>
              PDF
            </button>
          </div>
          <div className="text-panes">
            <div className="text-page" aria-label="Page">
              {page && (
                <div className="text-page-image" style={{ aspectRatio: `${page.width} / ${page.height}` }}>
                  <img src={page.image} alt={page.file} />
                  {letters
                    .filter((x) => view(x, readers).uncertain || x.sample_id === selected)
                    .map((x) => (
                      <span
                        key={x.sample_id}
                        ref={(el) => {
                          if (el) boxRefs.current.set(x.sample_id, el);
                        }}
                        className={`text-box${view(x, readers).uncertain ? " uncertain" : ""}${x.sample_id === selected ? " selected" : ""}`}
                        title={`${shown(x, script, readers)}${view(x, readers).uncertain ? " (uncertain)" : ""}`}
                        onClick={() => pick(x.sample_id, "page")}
                        style={{
                          left: `${(100 * x.box[0]) / page.width}%`,
                          top: `${(100 * x.box[1]) / page.height}%`,
                          width: `${(100 * x.box[2]) / page.width}%`,
                          height: `${(100 * x.box[3]) / page.height}%`,
                        }}
                      />
                    ))}
                </div>
              )}
            </div>
            <div className="text-text" aria-label="Text">
              {!text ? (
                <p className="muted">
                  {page && converted.has(page.id) ? "Loading…" : "This page is not converted yet: Convert this page."}
                </p>
              ) : (
                <>
                  <p className="small muted">
                    {uncertainCount} uncertain letters (highlighted) ·{" "}
                    {readers === "tesseract" ? "as Tesseract read it" : `read by ${text.readers.replace("+", " and ") || "nothing"}`}
                  </p>
                  <div className={`text-lines ${script}`} lang={script === "gujarati" ? "gu" : "sa"}>
                    {text.lines.map((line, i) => (
                      <div key={i} className="text-line">
                        {line.map((x) => (
                          <span key={x.sample_id}>
                            {x.space && " "}
                            <span
                              ref={(el) => {
                                if (el) letterRefs.current.set(x.sample_id, el);
                              }}
                              className={`text-letter${view(x, readers).uncertain ? " uncertain" : ""}${view(x, readers).dev ? "" : " unknown"}${
                                x.sample_id === selected ? " selected" : ""
                              }`}
                              onClick={() => pick(x.sample_id, "text")}
                            >
                              {shown(x, script, readers)}
                            </span>
                          </span>
                        ))}
                      </div>
                    ))}
                  </div>
                  {sel && (
                    <p className="small text-letter-info" aria-live="polite">
                      <strong>{shown(sel, script, readers)}</strong> · confidence {Math.round(view(sel, readers).conf * 100)}%
                      {view(sel, readers).uncertain && " · uncertain"} ·{" "}
                      {sel.readings.length
                        ? sel.readings.map(([r, t, v]) => `${r === "groups" ? "your groups" : "Tesseract"}: ${t || "—"} (${v})`).join(" · ")
                        : "no reader could read it"}
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
              {plainLines(t, script, readers).map((l, i) => (
                <p key={i}>{l}</p>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
