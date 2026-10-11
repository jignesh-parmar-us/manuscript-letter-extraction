// Read Book → Line truth: what each line really says, checked by hand, as the test set every way of
// reading is compared on. A line image is shown with Tesseract's reading of the whole line (no letter
// cutting); correct it to what the line says, in Gujarati or Devanagari, and press Enter to save and go
// to the next line. The text is kept per line, independent of the letter cuts. The on-screen letters
// insert at the cursor: click where a letter is wrong, remove it (⌫) and click the right one.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Book, TruthLine, TruthProgress } from "../api";
import ErrorBox from "../components/ErrorBox";
import LetterPalette, { toGujarati } from "../components/LetterPalette";
import { go } from "../route";

interface Props {
  book: Book;
  pageId: number | null;
}

export default function TruthView({ book, pageId }: Props) {
  const [progress, setProgress] = useState<TruthProgress | null>(null);
  const [lines, setLines] = useState<TruthLine[]>([]);
  const [at, setAt] = useState(0);
  const [text, setText] = useState("");
  const [tesseract, setTesseract] = useState<{ dev: string; guj: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [showLetters, setShowLetters] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);

  const loadProgress = useCallback(() => api.truthProgress(book.id).then(setProgress, setError), [book.id]);
  useEffect(() => {
    loadProgress();
  }, [loadProgress]);

  // no page chosen: the first page with lines left to check
  useEffect(() => {
    if (pageId !== null || !progress?.pages.length) return;
    const next = progress.pages.find((p) => p.checked < p.lines) ?? progress.pages[0];
    go(`/books/${book.id}/truth/${next.page_id}`);
  }, [pageId, progress, book.id]);

  useEffect(() => {
    setLines([]);
    if (pageId === null) return;
    api.truthLines(pageId).then((ls) => {
      setLines(ls);
      const first = ls.findIndex((l) => l.truth_dev === null);
      setAt(first >= 0 ? first : 0);
    }, setError);
  }, [pageId]);

  const line = lines[at];
  // the text to start from: the checked text, or Tesseract's reading of the whole line
  useEffect(() => {
    setTesseract(null);
    if (!line) return;
    setText(line.truth_guj ?? "");
    let live = true;
    api.lineTesseract(line.line_id).then(
      (t) => {
        if (!live) return;
        setTesseract({ dev: t.text_dev, guj: t.text_guj });
        if (line.truth_guj === null) setText(t.text_guj);
        input.current?.focus();
      },
      (e) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [line?.line_id]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Put `s` in place of the selection (or at the cursor) and keep the cursor after it. */
  function insert(s: string) {
    const el = input.current;
    const a = el?.selectionStart ?? text.length;
    const b = el?.selectionEnd ?? text.length;
    const next = text.slice(0, a) + s + text.slice(b);
    setText(next);
    window.requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(a + s.length, a + s.length);
    });
  }
  /** Remove the selection, or the character before the cursor. */
  function backspace() {
    const el = input.current;
    const a = el?.selectionStart ?? text.length;
    const b = el?.selectionEnd ?? text.length;
    const from = a < b ? a : a - (Array.from(text.slice(0, a)).pop()?.length ?? 0);
    setText(text.slice(0, from) + text.slice(b));
    window.requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(from, from);
    });
  }

  const pages = progress?.pages ?? [];
  const pageAt = pages.findIndex((p) => p.page_id === pageId);

  function move(step: number) {
    const k = at + step;
    if (k >= 0 && k < lines.length) setAt(k);
    else if (k >= lines.length && pageAt >= 0 && pageAt < pages.length - 1) go(`/books/${book.id}/truth/${pages[pageAt + 1].page_id}`);
    else if (k < 0 && pageAt > 0) go(`/books/${book.id}/truth/${pages[pageAt - 1].page_id}`);
  }

  async function save(value: string) {
    if (!line) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.saveTruth(line.line_id, value, tesseract?.dev ?? "");
      setLines((ls) => ls.map((l) => (l.line_id === line.line_id ? { ...l, truth_dev: r.truth_dev, truth_guj: r.truth_guj } : l)));
      loadProgress();
      if (r.truth_dev !== null) move(1);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const page = pages[pageAt];
  return (
    <div className="truth-view">
      <ErrorBox error={error} onClose={() => setError(null)} />
      <p className="small muted">
        Type what each line really says, to measure every way of reading on text you checked. Tesseract's reading of the
        whole line is filled in: correct it (Gujarati or Devanagari) and press <strong>Enter</strong> to save and go on.
        30 to 50 lines from a few pages are enough to start.
      </p>
      <div className="row truth-tools">
        <select
          aria-label="Page"
          value={pageId ?? ""}
          onChange={(e) => go(`/books/${book.id}/truth/${e.target.value}`)}
          disabled={!pages.length}
        >
          {pages.map((p) => (
            <option key={p.page_id} value={p.page_id}>
              {p.file} ({p.checked} of {p.lines} checked)
            </option>
          ))}
        </select>
        <span className="small muted" aria-label="Progress">
          {progress ? `${progress.checked} lines checked in this book` : ""}
        </span>
      </div>
      {!pages.length && progress && (
        <p className="muted">No Read Book pages are cut yet: upload the book and cut its pages first (Upload &amp; capture).</p>
      )}
      {line && (
        <div className="card truth-card">
          <div className="row small muted">
            Line {at + 1} of {lines.length}
            {page ? ` · ${page.file}` : ""}
            {line.truth_dev !== null && <span className="badge ok">checked</span>}
          </div>
          <img className="truth-line" src={line.image} alt={`line ${at + 1}`} />
          <input
            ref={input}
            className="truth-input"
            aria-label="What the line says"
            lang="gu"
            value={text}
            disabled={busy}
            placeholder={tesseract ? "" : "Reading the line…"}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && text.trim()) save(text);
            }}
          />
          {text && /[ऀ-ॿ]/.test(text) && (
            <p className="small muted">As Gujarati: {toGujarati(text)}</p>
          )}
          <div className="row">
            <button className="primary" disabled={busy || !text.trim()} onClick={() => save(text)}>
              Save and next
            </button>
            <button disabled={busy || (at === 0 && pageAt <= 0)} onClick={() => move(-1)}>
              ◀ Previous
            </button>
            <button disabled={busy} onClick={() => move(1)}>
              Skip ▶
            </button>
            <button className="link" disabled={!tesseract} onClick={() => tesseract && setText(tesseract.guj)}>
              Start again from Tesseract's reading
            </button>
            {line.truth_dev !== null && (
              <button className="link" disabled={busy} onClick={() => save("")}>
                Not checked
              </button>
            )}
            <button className="link" onClick={() => setShowLetters((v) => !v)}>
              {showLetters ? "Hide letters" : "Letters…"}
            </button>
          </div>
          {showLetters && (
            <LetterPalette
              onKey={insert}
              onBackspace={backspace}
              extra={
                <button onClick={() => insert(" ")} aria-label="Space">
                  Space
                </button>
              }
            />
          )}
          {tesseract && <p className="small muted">Tesseract read: {tesseract.guj || "nothing"}</p>}
        </div>
      )}
      {lines.length > 0 && (
        <ol className="truth-lines small" aria-label="Lines of the page">
          {lines.map((l, i) => (
            <li key={l.line_id} className={i === at ? "current" : ""}>
              <button className="link" onClick={() => setAt(i)}>
                {l.truth_dev !== null ? "✓ " : ""}
                {l.truth_guj ?? `line ${i + 1}`}
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
