// Read Book → Text (C16b): a page and its converted text, side by side or one above the other.
// Printed books: "Tesseract only" shows what Tesseract read; "Tesseract + your groups" adds the labelled
// groups' second opinion and the uncertain marks it brings (both are stored, so switching is instant).
// Uncertain letters are highlighted in the text and on the page; clicking a letter shows it on the
// page, and clicking a box on the page shows its letter in the text. Convert the page or all pages
// (a background job; each page is kept as soon as it is done). Downloads: .txt and Word from the
// backend; PDF printed by the browser from the text; a picture (.png) of the text drawn by the browser,
// which joins Gujarati letters correctly.
//
// Proofreading (C17): the selected letter can be corrected (it labels its sample: one undoable action,
// and the letter joins the book's Training Data), split in two, joined with the next letter or deleted.
// A line is marked proofread with its ✓ button; converting again keeps proofread lines as they are.
//
// The section opens with a choice of how the text is read: "Whole lines (Tesseract)" (WholeLinesView:
// Tesseract reads each line image as it is, no letters cut; measured best), "Whole lines (our reader)" (the
// same view with the line search's reading, its Retrain and its fold-fair Measure) or "Cut letters" (this view).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ActionResult, Book, Marker, PageInfo, PageText, ProofreadStats, Readers, TextLetter, TextSummary } from "../api";
import ErrorBox from "../components/ErrorBox";
import LabelPicker from "../components/LabelPicker";
import { PageImagesPdf, PrintPages } from "../components/PageDownloads";
import { useJob } from "../components/useJob";
import { go } from "../route";
import { JobPanel } from "./Capture";
import PagePicker from "./PagePicker";
import LineCrop, { AlignedText, unionBox } from "./LineCrop";
import WholeLinesView, { useArrowKeys } from "./WholeLinesView";

/** Whole page (the page above its text) or Line by line (one line cropped from the page). */
export type Layout = "page" | "line";

/** In Whole page: the page image with its text below, or every line as a strip with its text under it. */
export type PageStyle = "image" | "strips";

function stored<T extends string>(key: string, values: T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && values.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // a private window: the choice lasts until the page is closed
  }
}

function storedLayout(): Layout {
  try {
    return localStorage.getItem("text-layout") === "line" ? "line" : "page";
  } catch {
    return "page";
  }
}
type Script = "gujarati" | "devanagari";
const FONT = `"Noto Sans Gujarati", "Gujarati Sangam MN", "Shruti", "Noto Sans Devanagari", sans-serif`;

interface Props {
  book: Book;
  pageId: number | null;
  onChanged: () => void;
}

const READER_NAMES: Record<string, string> = {
  tesseract: "Tesseract",
  reader: "your letter reader",
  groups: "your groups",
  language: "the language model",
};

/** The readers of a converted page, in words ("Tesseract, your letter reader and your groups"). */
function readerWords(readers: string): string {
  const names = readers.split("+").filter(Boolean).map((r) => READER_NAMES[r] ?? r);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0] ?? "nothing";
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

type Mode = "lines" | "search" | "letters";

function storedMode(): Mode {
  return stored<Mode>("text-mode", ["lines", "search", "letters"], "lines");
}

/** Read Book → Text: whole lines (Tesseract alone) or cut letters (with your groups, reader, language model). */
export default function TextView(props: Props) {
  const [mode, setMode] = useState<Mode>(storedMode);
  const [layout, setLayout] = useState<Layout>(storedLayout);
  const [pageStyle, setPageStyle] = useState<PageStyle>(() => stored("text-page-style", ["image", "strips"], "strips"));
  const [aligned, setAligned] = useState<boolean>(() => stored("text-aligned", ["on", "off"], "on") === "on");
  function chooseLayout(l: Layout) {
    setLayout(l);
    try {
      localStorage.setItem("text-layout", l);
    } catch {
      // a private window: the choice lasts until the page is closed
    }
  }
  function choose(m: Mode) {
    setMode(m);
    try {
      localStorage.setItem("text-mode", m);
    } catch {
      // a private window: the choice lasts until the page is closed
    }
  }
  return (
    <>
      <div className="row text-mode" role="group" aria-label="How the text is read">
        <button className={mode === "lines" ? "tab active" : "tab"} onClick={() => choose("lines")}
          title="Tesseract reads each line image whole; no letters are cut">
          Whole lines (Tesseract)
        </button>
        <button className={mode === "search" ? "tab active" : "tab"} onClick={() => choose("search")}
          title="Our reader (the line search) reads each line without Tesseract, from this book's reviewed letters">
          Whole lines (our reader)
        </button>
        <button className={mode === "letters" ? "tab active" : "tab"} onClick={() => choose("letters")}
          title="The page is cut into letters, read by Tesseract and checked with your groups, reader and language model; letters can be corrected">
          Cut letters
        </button>
        <span className="spacer" />
        <div className="row" role="group" aria-label="Layout">
          <button className={layout === "page" ? "tab active" : "tab"} onClick={() => chooseLayout("page")}
            title="The page above its text">
            Whole page
          </button>
          <button className={layout === "line" ? "tab active" : "tab"} onClick={() => chooseLayout("line")}
            title="One line at a time, cropped from the page, with ◀ ▶ between lines">
            Line by line
          </button>
        </div>
        {layout === "page" && (
          <div className="row" role="group" aria-label="Whole page as">
            <button className={pageStyle === "image" ? "tab active" : "tab"} title="The page image with its text below"
              onClick={() => { setPageStyle("image"); remember("text-page-style", "image"); }}>
              As a page
            </button>
            <button className={pageStyle === "strips" ? "tab active" : "tab"} title="Every line as its strip of the page, with its text under it"
              onClick={() => { setPageStyle("strips"); remember("text-page-style", "strips"); }}>
              Line strips
            </button>
          </div>
        )}
        {!(layout === "page" && pageStyle === "image") && (
          <label className="row small" title="The text under each line image, every akshara under its letter">
            <input type="checkbox" checked={aligned}
              onChange={(e) => { setAligned(e.target.checked); remember("text-aligned", e.target.checked ? "on" : "off"); }} />
            Aligned text
          </label>
        )}
        <span className="small muted mode-note">
          {mode === "lines"
            ? "Each line image goes to Tesseract as it is: no letters are cut."
            : mode === "search"
              ? "Our reader slides along each line and reads the letters it learned from your reviewed groups: no Tesseract."
              : "Each cut letter is read and checked with your groups, letter reader and language model; proofread here."}
        </span>
      </div>
      {mode === "lines" || mode === "search" ? (
        <WholeLinesView key={mode} {...props} engine={mode === "search" ? "search" : "tesseract"} layout={layout}
          pageStyle={pageStyle} aligned={aligned} />
      ) : (
        <LettersView {...props} layout={layout} pageStyle={pageStyle} aligned={aligned} />
      )}
    </>
  );
}

function LettersView({ book, pageId, onChanged, layout, pageStyle, aligned }: Props & { layout: Layout; pageStyle: PageStyle; aligned: boolean }) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [converted, setConverted] = useState<Map<number, TextSummary>>(new Map()); // converted pages
  const [stats, setStats] = useState<ProofreadStats | null>(null);
  const [text, setText] = useState<PageText | null>(null);
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
  const [splitting, setSplitting] = useState(false); // choosing where to cut the selected letter
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.pages(book.id, "read").then(setPages, setError);
    api.bookTexts(book.id).then((ts) => setConverted(new Map(ts.map((t) => [t.page_id, t]))), setError);
    api.proofreadStats(book.id).then(setStats, () => setStats(null));
  }, [book.id, version]);
  // no page chosen: open the first one
  useEffect(() => {
    if (pageId === null && pages.length) go(`/books/${book.id}/text/${pages[0].id}`);
  }, [pageId, pages, book.id]);
  // the page's text again when it is converted (again), not after each correction
  const convertedAt = pageId !== null && converted.has(pageId) ? converted.get(pageId)!.converted_at ?? "" : null;
  useEffect(() => {
    setText(null);
    setSelected(null);
    if (pageId === null || convertedAt === null) return;
    api.pageText(pageId).then(setText, setError);
  }, [pageId, convertedAt]);

  /** Run a change of the page's letters, then show the page's text as it is now. */
  async function act(run: () => Promise<ActionResult | PageText>, after?: (r: ActionResult) => void) {
    if (pageId === null) return false;
    setBusy(true);
    setError(null);
    try {
      const r = await run();
      if ("lines" in r) setText(r as PageText);
      else {
        setText(await api.pageText(pageId));
        after?.(r as ActionResult);
      }
      setVersion((v) => v + 1);
      return true;
    } catch (e) {
      setError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }

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
  const hasReader = !!text?.readers.includes("reader");
  const readers: Readers = hasTesseract ? readersChoice : "both";
  const uncertainCount = readers === "tesseract" ? text?.uncertain_tesseract ?? 0 : text?.uncertain ?? 0;
  const sel = letters.find((x) => x.sample_id === selected) ?? null;
  const selLine = text && sel ? text.lines.find((l) => l.includes(sel)) ?? [] : [];
  const selNext = sel ? selLine[selLine.indexOf(sel) + 1] : undefined;
  useEffect(() => setSplitting(false), [selected]);

  function nextUncertain() {
    const at = letters.findIndex((x) => x.sample_id === selected);
    const after = [...letters.slice(at + 1), ...letters.slice(0, at + 1)];
    const next = after.find((x) => view(x, readers).uncertain || !view(x, readers).dev);
    if (next) pick(next.sample_id, "text");
  }

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

  const nConverted = pages.filter((p) => converted.has(p.id)).length;
  const states = text?.line_states ?? [];

  const lineIdxOf = (id: number | null) => (text && id !== null ? text.lines.findIndex((l) => l.some((x) => x.sample_id === id)) : -1);
  const [lineIdx, setLineIdx] = useState(0);
  useEffect(() => setLineIdx(0), [pageId]);
  useEffect(() => {
    const i = lineIdxOf(selected);
    if (i >= 0) setLineIdx(i);
  }, [selected, text]); // eslint-disable-line react-hooks/exhaustive-deps
  function toLine(i: number) {
    if (!text || i < 0 || i >= text.lines.length) return;
    setLineIdx(i);
    setSelected(text.lines[i][0]?.sample_id ?? null);
  }
  const lineBox = text && text.lines[lineIdx] ? unionBox(text.lines[lineIdx].map((x) => x.box)) : null;

  // ← → between letters (in reading order), ↑ ↓ between lines
  const onMove = useCallback(
    (step: number, line: number) => {
      if (!text || !letters.length) return;
      if (line) {
        const cur = Math.max(0, lineIdxOf(selected) >= 0 ? lineIdxOf(selected) : lineIdx);
        let i = cur + line;
        while (i >= 0 && i < text.lines.length && !text.lines[i].length) i += line;
        if (i >= 0 && i < text.lines.length) toLine(i);
        return;
      }
      const at = letters.findIndex((x) => x.sample_id === selected);
      const k = at < 0 ? (step > 0 ? 0 : letters.length - 1) : at + step;
      if (k >= 0 && k < letters.length) setSelected(letters[k].sample_id);
    },
    [text, letters, selected, lineIdx], // eslint-disable-line react-hooks/exhaustive-deps
  );
  useArrowKeys(onMove);

  const lineRefs = useRef(new Map<number, HTMLElement>());
  useEffect(() => {
    if (layout === "page") lineRefs.current.get(lineIdx)?.scrollIntoView?.({ block: "nearest" });
  }, [lineIdx, layout]);

  /** A line's letters as running text (clickable), with its ✓ if `withMark`. */
  const plainLine = (line: TextLetter[], i: number, withMark: boolean) => (
    <div key={i} className={`text-lines ${script}`} lang={script === "gujarati" ? "gu" : "sa"}>
      <div className={`text-line${states[i] ? ` ${states[i]}` : ""}`}>
        {line.map((x) => (
          <span key={x.sample_id}>
            {x.space && " "}
            <span
              ref={(el) => {
                if (el) letterRefs.current.set(x.sample_id, el);
              }}
              className={`text-letter${view(x, readers).uncertain ? " uncertain" : ""}${view(x, readers).dev ? "" : " unknown"}${
                readers === "both" && x.lm_from !== undefined ? " lm" : ""
              }${x.sample_id === selected ? " selected" : ""}`}
              onClick={() => pick(x.sample_id, "text")}
            >
              {shown(x, script, readers)}
            </span>
          </span>
        ))}
        {withMark && proofButton(i)}
      </div>
    </div>
  );

  /** A line cropped from the page, with its uncertain and selected letters, and its text under it (aligned or not). */
  const cropAndText = (line: TextLetter[], box: [number, number, number, number], i: number) =>
    page && (
      <>
        <LineCrop
          page={page}
          box={box}
          marks={line
            .filter((x) => view(x, readers).uncertain || x.sample_id === selected)
            .map((x) => ({
              key: x.sample_id,
              box: x.box,
              className: `${view(x, readers).uncertain ? "uncertain " : ""}${x.sample_id === selected ? "selected" : ""}`.trim(),
              title: shown(x, script, readers),
              onClick: () => setSelected(x.sample_id),
            }))}
        />
        {!aligned ? plainLine(line, i, false) : <AlignedText
          page={page}
          box={box}
          items={line.map((x) => ({
            key: x.sample_id,
            box: x.box,
            text: shown(x, script, readers),
            className: `${view(x, readers).uncertain ? "uncertain " : ""}${view(x, readers).dev ? "" : "unknown "}${
              readers === "both" && x.lm_from !== undefined ? "lm " : ""}${x.sample_id === selected ? "selected" : ""}`.trim(),
            onClick: () => setSelected(x.sample_id),
          }))}
        />}
      </>
    );

  const proofButton = (i: number) =>
    text && (text.lines[i] ?? []).length > 0 && (
      <button
        className={`proofread-mark${states[i] === "proofread" ? " done" : ""}`}
        disabled={busy}
        aria-label={`Line ${i + 1} ${states[i] === "proofread" ? "proofread" : "not proofread"}`}
        title={
          states[i] === "proofread"
            ? "Proofread: click to undo"
            : states[i] === "changed"
              ? "Changed since it was proofread: click to mark it proofread again"
              : "Mark this line proofread (its text is right)"
        }
        onClick={() => act(() => api.proofread(pageId!, i, states[i] !== "proofread"))}
      >
        {states[i] === "changed" ? "⚠" : "✓"}
      </button>
    );

  const summaryBlock = text && (
    <>
                  <p className="small muted">
                    {uncertainCount} uncertain letters (highlighted) ·{" "}
                    {readers === "tesseract" ? "as Tesseract read it" : `read by ${readerWords(text.readers)}`}
                    {" · "}
                    {text.proofread ?? 0} of {text.lines.length} lines proofread
                    {!!text.corrected && ` · ${text.corrected} letters corrected`}{" "}
                    <button className="link small" onClick={nextUncertain} disabled={!uncertainCount && !letters.some((x) => !x.text_dev)}>
                      Next uncertain ▶
                    </button>
                  </p>
                  {stats && stats.lines > 0 && stats.cer !== null && (
                    <p className="small muted" aria-label="Measured">
                      Measured on your {stats.lines} proofread lines: {(100 * stats.cer).toFixed(1)}% of the characters were read
                      wrong{stats.cer_tesseract !== null && ` (Tesseract alone ${(100 * stats.cer_tesseract).toFixed(1)}%)`}.
                    </p>
                  )}
    </>
  );

  const editorBlock = (
    <>
                  {sel && (
                    <div className="text-editor" aria-label="Letter">
                      <p className="small text-letter-info" aria-live="polite">
                        <strong>{shown(sel, script, readers)}</strong>
                        {readers === "both" && sel.lm_from !== undefined && sel.source !== "label" && (
                          <> · the language model changed it from {sel.lm_from || "?"}</>
                        )}
                        {sel.source === "label" ? (
                          <> · corrected by you{sel.read_dev !== undefined && ` (read as ${sel.read_dev || "?"})`}</>
                        ) : (
                          <>
                            {" "}
                            · confidence {Math.round(view(sel, readers).conf * 100)}%{view(sel, readers).uncertain && " · uncertain"} ·{" "}
                            {sel.readings.length
                              ? sel.readings
                                  .map(([r, t, v]) => `${READER_NAMES[r] ?? r}: ${t || "—"} (${r === "reader" ? `${Math.round(v * 100)}%` : v})`)
                                  .join(" · ")
                              : "no reader could read it"}
                          </>
                        )}
                      </p>
                      <div className="row">
                        {sel.image && (
                          <img
                            className={`text-editor-letter${splitting ? " cutting" : ""}`}
                            src={sel.image}
                            alt={`letter ${sel.sample_id}`}
                            title={splitting ? "Click where the two letters meet" : undefined}
                            onClick={(e) => {
                              if (!splitting) return;
                              const r = e.currentTarget.getBoundingClientRect();
                              const x = Math.round(sel.box[0] + ((e.clientX - r.left) / r.width) * sel.box[2]);
                              act(() => api.split(book.id, sel.sample_id, x), (res) => {
                                const first = (res as { samples?: { id: number }[] }).samples?.[0];
                                if (first) setSelected(first.id);
                              });
                            }}
                          />
                        )}
                        <LabelPicker
                          key={sel.sample_id}
                          bookId={book.id}
                          current={{ dev: view(sel, readers).dev, guj: view(sel, readers).guj }}
                          disabled={busy}
                          saveText="Correct"
                          canClear={false}
                          compact
                          onSave={(t) => act(() => api.labelSamples(book.id, [sel.sample_id], t))}
                        />
                      </div>
                      <div className="row small">
                        <button disabled={busy || !sel.image} onClick={() => setSplitting((v) => !v)}
                          title="The box holds two letters: click on the picture where they meet">
                          {splitting ? "Cancel split" : "Two letters…"}
                        </button>
                        <button
                          disabled={busy || !selNext}
                          onClick={() =>
                            selNext &&
                            act(() => api.join(book.id, [sel.sample_id, selNext.sample_id]), (res) => {
                              const id = (res as { sample?: { id: number } }).sample?.id;
                              if (id) setSelected(id);
                            })
                          }
                          title="This letter and the next one are one letter"
                        >
                          Join with the next
                        </button>
                        <button disabled={busy} onClick={() => act(() => api.deleteSamples(book.id, [sel.sample_id]))}
                          title="A speck or a stroke that is not a letter">
                          Not a letter
                        </button>
                        <button disabled={busy} onClick={() => act(() => api.undo(book.id))} title="Undo the last change of the book">
                          Undo
                        </button>
                        {splitting && <span className="muted">Click on the picture where the two letters meet.</span>}
                      </div>
                    </div>
                  )}
    </>
  );

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
        {hasTesseract && (
          <div className="row" role="group" aria-label="Readers">
            <button className={readers === "tesseract" ? "tab active" : "tab"} onClick={() => chooseReaders("tesseract")}
              title="What Tesseract read, as it is">
              Tesseract only
            </button>
            <button className={readers === "both" ? "tab active" : "tab"} onClick={() => chooseReaders("both")}
              title={hasReader
                ? "Tesseract, your letter reader and your labelled groups vote on every letter: disagreements are marked uncertain"
                : "Tesseract checked against your labelled groups: disagreements are marked uncertain"}>
              {hasReader ? "Tesseract + your reader and groups" : "Tesseract + your groups"}
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
            <PageImagesPdf bookId={book.id} pageId={page?.id ?? null} nPages={pages.length} />
          </div>
          {layout === "line" ? (
            !text || !page ? (
              <p className="muted">{page && converted.has(page.id) ? "Loading…" : "This page is not converted yet: Convert this page."}</p>
            ) : (
              <div className="line-by-line" aria-label="Line by line">
                {summaryBlock}
                <div className="row line-nav">
                  <button disabled={lineIdx === 0} onClick={() => toLine(lineIdx - 1)} aria-label="Previous line">
                    ◀ Previous line
                  </button>
                  <span className="small muted">
                    Line {lineIdx + 1} of {text.lines.length}
                  </span>
                  <button disabled={lineIdx >= text.lines.length - 1} onClick={() => toLine(lineIdx + 1)} aria-label="Next line">
                    Next line ▶
                  </button>
                  {proofButton(lineIdx)}
                </div>
                {lineBox && text.lines[lineIdx] && cropAndText(text.lines[lineIdx], lineBox, lineIdx)}
                {editorBlock}
              </div>
            )
          ) : (
            pageStyle === "image" ? (
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
                    <p className="muted">{page && converted.has(page.id) ? "Loading…" : "This page is not converted yet: Convert this page."}</p>
                  ) : (
                    <>
                      {summaryBlock}
                      {text.lines.map((line, i) => plainLine(line, i, line.length > 0))}
                      {editorBlock}
                    </>
                  )}
                </div>
              </div>
            ) : !text || !page ? (
              <p className="muted">{page && converted.has(page.id) ? "Loading…" : "This page is not converted yet: Convert this page."}</p>
            ) : (
              <div className="interlinear" aria-label="Lines">
                {summaryBlock}
                {text.lines.map((line, i) => {
                  const box = unionBox(line.map((x) => x.box));
                  if (!box) return null;
                  return (
                    <div key={i} ref={(el) => { if (el) lineRefs.current.set(i, el); }}
                      className={`interlinear-line${i === lineIdx ? " selected" : ""}${states[i] ? ` ${states[i]}` : ""}`}>
                      {cropAndText(line, box, i)}
                      <div className="row line-tools-row">
                        <span className="small muted">Line {i + 1}</span>
                        {proofButton(i)}
                      </div>
                      {i === lineIdx && editorBlock}
                    </div>
                  );
                })}
              </div>
            )
          )}
        </>
      )}
      {printing && (
        <PrintPages
          pages={printing.map((t) => ({ key: t.page_id, title: pages.find((p) => p.id === t.page_id)?.file,
            lines: plainLines(t, script, readers) }))}
          onDone={() => setPrinting(null)}
        />
      )}
    </div>
  );
}
