// The Try it tab (F6): type Devanagari and see it in the newest build of the font, then the same text
// marked akshara by akshara: the book's own glyph, pieced together from the book's glyphs, holding a
// filled letter, or holding a missing one (a box). The font is loaded from the build's own file name, so
// a new build is never shown from an old copy.
import { useEffect, useState } from "react";
import { api, BuildState, fontFileUrl, TryAkshara, TryResult } from "./api";
import { go } from "./route";

const SAMPLES = ["श्री स्वामिनारायण भगवान", "वचनामृत गढडा प्रथम प्रकरण", "भक्त धर्म ज्ञान वैराग्य", "किं कृष्ण गुरु ॥ १२"];
const LEGEND: [TryAkshara["kind"], string][] = [
  ["book", "the book's own glyph"],
  ["pieced", "pieced together from the book's glyphs"],
  ["filled", "holds a letter filled from the normal font"],
  ["missing", "holds a missing letter (a box)"],
  ["other", "not Devanagari: not in this font"],
];

export default function TryIt({ fontId }: { fontId: string }) {
  const [state, setState] = useState<BuildState | null>(null);
  const [text, setText] = useState(SAMPLES[0]);
  const [size, setSize] = useState(48);
  const [result, setResult] = useState<TryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.buildState(fontId).then(setState, (e: Error) => setError(e.message));
  }, [fontId]);
  const report = state?.report;
  useEffect(() => {
    // asked again only after a short pause in typing
    if (!report) return;
    const timer = window.setTimeout(() => api.tryText(fontId, text).then(setResult, (e: Error) => setError(e.message)), 300);
    return () => window.clearTimeout(timer);
  }, [fontId, text, report]);

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
  return (
    <>
      <style>{`@font-face { font-family: "${family}"; src: url("${url}") format("truetype"); }`}</style>
      {error && <p className="error-text">{error}</p>}
      <div className="row toolbar">
        {SAMPLES.map((s) => (
          <button key={s} onClick={() => setText(s)}>{s}</button>
        ))}
      </div>
      <textarea className="try-text" value={text} onChange={(e) => setText(e.target.value)} rows={3}
                aria-label="Text to try" style={{ fontFamily: `"${family}", serif`, fontSize: size }} />
      <div className="row">
        <label className="small">
          Size <input type="range" min={16} max={120} value={size} onChange={(e) => setSize(Number(e.target.value))} /> {size} px
        </label>
        <span className="muted small">Build {report.build}.</span>
        <a href={url} download={report.file}>Download {report.file}</a>
        <a href="/help/font.html" target="_blank" rel="noreferrer">How to install it and use it in Word</a>
      </div>
      {result && (
        <div className="card">
          <p className="try-marked" style={{ fontFamily: `"${family}", serif`, fontSize: Math.max(28, size * 0.75) }}>
            {result.aksharas.map((a, i) => (
              <span key={i} className={`ak ${a.kind}`} title={LEGEND.find(([k]) => k === a.kind)?.[1]}>{a.text}</span>
            ))}
          </p>
          <div className="row small">
            {LEGEND.map(([k, text]) => (
              <span key={k} className="legend">
                <span className={`ak ${k}`}>क</span> {text}: <strong>{result.counts[k] ?? 0}</strong>
              </span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
