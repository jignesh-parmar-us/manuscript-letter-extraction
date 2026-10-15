// The Try it tab (F6, F7): type Devanagari (with the keyboard or the letters palette) and see it in the newest
// build of the font. One check line below the box says whether every akshara is the book's own, and lists
// the ones that are not (click one to select it in the box). The text can be saved as a test text (measured
// after every build, Build tab) and downloaded as an image, text, PDF or Word document in the font.
// The font is loaded from the build's own file name, so a new build is never shown from an old copy.
// Layout: on a wide window the text (left) and the letters palette (right) side by side, the palette
// staying in view and scrolling inside itself; on a narrow one the palette goes under the box. The
// palette can be hidden (remembered per viewer).
import { useEffect, useRef, useState } from "react";
import { api, BuildState, fontFileUrl, TestText, TryAkshara, TryResult } from "./api";
import { aksharaStartBefore } from "./letters";
import LetterPalette, { KIND_TEXT } from "./LetterPalette";
import { go } from "./route";

const SAMPLES = ["श्री स्वामिनारायण भगवान", "वचनामृत गढडा प्रथम प्रकरण", "भक्त धर्म ज्ञान वैराग्य", "किं कृष्ण गुरु ॥ १२"];
const NOT_BOOK = ["pieced", "generated", "filled", "missing"];

function reason(a: TryAkshara): string {
  if (a.kind === "pieced") return "pieced";
  return (a.detail ?? []).map((d) => `${d.kind} ${d.char}`).join(", ") || a.kind;
}

export function checkLine(result: TryResult) {
  const aks = result.aksharas.filter((a) => a.kind !== "space" && a.kind !== "other");
  const others = result.aksharas.filter((a) => a.kind === "other");
  const own = aks.filter((a) => a.kind === "book").length;
  const notOwn = new Map<string, { a: TryAkshara; n: number }>();
  for (const a of aks.filter((a) => NOT_BOOK.includes(a.kind))) {
    const hit = notOwn.get(a.text);
    if (hit) hit.n += 1;
    else notOwn.set(a.text, { a, n: 1 });
  }
  return { total: aks.length, own, notOwn: [...notOwn.values()], others };
}

const SHOWN = "fm-palette-shown";
function loadShown(): boolean {
  try {
    return window.localStorage.getItem(SHOWN) !== "no";
  } catch {
    return true;
  }
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function TryIt({ fontId }: { fontId: string }) {
  const [state, setState] = useState<BuildState | null>(null);
  const [text, setText] = useState(SAMPLES[0]);
  const [size, setSize] = useState(48);
  const [result, setResult] = useState<TryResult | null>(null);
  const [texts, setTexts] = useState<TestText[]>([]);
  const [chosen, setChosen] = useState<string>("");
  const [naming, setNaming] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [shown, setShown] = useState(loadShown);
  const showPalette = (on: boolean) => {
    setShown(on);
    try {
      window.localStorage.setItem(SHOWN, on ? "yes" : "no");
    } catch {
      // private window: not kept
    }
  };
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const caret = useRef<number | null>(null);
  const fail = (e: Error) => setError(e.message);

  useEffect(() => {
    api.buildState(fontId).then(setState, fail);
    api.texts(fontId).then(setTexts, fail);
  }, [fontId]);
  const report = state?.report;
  useEffect(() => {
    // asked again only after a short pause in typing
    if (!report) return;
    const timer = window.setTimeout(() => api.tryText(fontId, text).then(setResult, fail), 300);
    return () => window.clearTimeout(timer);
  }, [fontId, text, report]);
  useEffect(() => {
    // after a key of the palette: the cursor goes back into the box, after what was typed
    if (caret.current === null) return;
    box.current?.focus();
    box.current?.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  }, [text]);

  /** Put `s` in place of the selection (or at the cursor) and keep the cursor after it. */
  function insert(s: string) {
    const el = box.current;
    const a = el?.selectionStart ?? text.length;
    const b = el?.selectionEnd ?? text.length;
    caret.current = a + s.length;
    setText(text.slice(0, a) + s + text.slice(b));
  }
  /** Remove the selection, or the character (or the akshara) before the cursor. */
  function remove(akshara: boolean) {
    const el = box.current;
    const a = el?.selectionStart ?? text.length;
    const b = el?.selectionEnd ?? text.length;
    const from = a < b ? a : akshara ? aksharaStartBefore(text, a) : a - (Array.from(text.slice(0, a)).pop()?.length ?? 0);
    caret.current = Math.max(0, from);
    setText(text.slice(0, Math.max(0, from)) + text.slice(b));
  }
  function select(a: TryAkshara) {
    box.current?.focus();
    box.current?.setSelectionRange(a.start, a.start + a.text.length);
  }

  async function download(fmt: "png" | "txt" | "pdf" | "docx") {
    setError(null);
    try {
      const blob = fmt === "txt"
        ? new Blob([text], { type: "text/plain;charset=utf-8" })
        : await api.exportText(fontId, fmt, text, fmt === "png" ? size * 2 : 18);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${(report?.family ?? "font").replace(/[^A-Za-z0-9]+/g, "-")}-${today()}.${fmt}`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    } catch (e) {
      fail(e as Error);
    }
  }
  function choose(id: string) {
    setChosen(id);
    const t = texts.find((x) => x.id === id);
    if (t) setText(t.text);
  }
  function saveText(name: string) {
    api.saveText(fontId, name, text).then((t) => {
      setTexts((all) => [...all, t]);
      setChosen(t.id);
      setNaming(null);
      setMessage(`Saved as test text "${t.name}": the Build tab measures the font on it after every build.`);
    }, fail);
  }
  function deleteText(id: string) {
    api.deleteText(fontId, id).then(() => {
      setTexts((all) => all.filter((t) => t.id !== id));
      setChosen("");
    }, fail);
  }

  if (!state) return error ? <div className="error" role="alert"><span>{error}</span></div> : <p className="muted">Loading…</p>;
  if (!report)
    return (
      <p>
        Build the font first:{" "}
        <button className="link" onClick={() => go(`/fonts/${fontId}/build`)}>Build tab</button>.
      </p>
    );
  const family = `fm-${fontId}-${report.build}`;
  const url = fontFileUrl(fontId, report.file);
  const check = result && checkLine(result);
  const mine = texts.find((t) => t.id === chosen && t.source === "yours");
  return (
    <>
      <style>{`@font-face { font-family: "${family}"; src: url("${url}") format("truetype"); }`}</style>
      {error && <p className="error-text">{error}</p>}
      <div className={`try-layout${shown ? " with-palette" : ""}`}>
      <div className="try-main">
      <div className="row toolbar">
        {SAMPLES.map((s) => (
          <button key={s} onClick={() => setText(s)}>{s}</button>
        ))}
        <select value={chosen} onChange={(e) => choose(e.target.value)} aria-label="Test texts">
          <option value="">Test texts…</option>
          {texts.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        {mine && <button className="link danger" onClick={() => deleteText(mine.id)}>Delete this test text</button>}
      </div>
      <textarea ref={box} className="try-text" value={text} onChange={(e) => setText(e.target.value)} rows={3}
                aria-label="Text to try" style={{ fontFamily: `"${family}", serif`, fontSize: size }} />
      {check && (
        <p className="check-line" aria-label="Check">
          {check.notOwn.length === 0 ? (
            <>✓ {check.total} {check.total === 1 ? "akshara" : "aksharas"}, all the book's own.</>
          ) : (
            <>
              {check.total} aksharas: {check.own} the book's own · not the book's own:{" "}
              {check.notOwn.map(({ a, n }) => (
                <button key={a.text} className={`link ak ${a.kind}`} onClick={() => select(a)} title={KIND_TEXT[a.kind]}
                        style={{ fontFamily: `"${family}", serif` }}>
                  {a.text}
                  <span className="muted small"> ({reason(a)}{n > 1 ? `, ×${n}` : ""})</span>
                </button>
              ))}
            </>
          )}
          {check.others.length > 0 && (
            <span className="muted"> · not Devanagari: {check.others.map((o) => o.text).join(" ")}</span>
          )}
        </p>
      )}
      <div className="row toolbar">
        {!shown && <button onClick={() => showPalette(true)}>Show letters</button>}
        <label className="small">
          Size <input type="range" min={16} max={120} value={size} onChange={(e) => setSize(Number(e.target.value))} /> {size} px
        </label>
        <span className="muted small">Build {report.build}.</span>
        <button onClick={() => navigator.clipboard?.writeText(text).then(() => setMessage("Copied: paste it anywhere and choose this font there."))}>Copy</button>
        <span className="muted small">Download the text:</span>
        <button onClick={() => download("png")}>Image</button>
        <button onClick={() => download("txt")}>Text</button>
        <button onClick={() => download("pdf")}>PDF</button>
        <button onClick={() => download("docx")}>Word</button>
        {naming === null ? (
          <button onClick={() => setNaming("")}>Save as test text</button>
        ) : (
          <form className="row" onSubmit={(e) => { e.preventDefault(); if (naming.trim()) saveText(naming); }}>
            <input value={naming} onChange={(e) => setNaming(e.target.value)} placeholder="Name of the test text" autoFocus aria-label="Name of the test text" />
            <button type="submit" disabled={!naming.trim()}>Save</button>
            <button type="button" onClick={() => setNaming(null)}>Cancel</button>
          </form>
        )}
      </div>
      {message && <p className="muted small">{message}</p>}
      <p className="small">
        <a href={url} download={report.file}>Download the font ({report.file})</a> ·{" "}
        <a href="/help/font.html" target="_blank" rel="noreferrer">How to install it and use it in Word</a>
      </p>
      </div>
      {shown && (
        <div className="try-palette">
          <LetterPalette family={family} labels={report.labels} filled={report.filled} generated={report.generated_chars} onKey={insert}
                         onBackspace={() => remove(false)} onBackspaceAkshara={() => remove(true)}
                         onHide={() => showPalette(false)} />
        </div>
      )}
      </div>
    </>
  );
}
