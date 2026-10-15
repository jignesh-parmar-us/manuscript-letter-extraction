// The Build tab (F5): what the font will draw in the book's letters, the missing characters (fill them from
// a normal Devanagari font, always marked as filled; "Generate" comes in the next phase), and Build, which
// writes the next version of the .ttf.
import { useEffect, useState } from "react";
import { api, BuildState, fontFileUrl, TextCoverage } from "./api";

export default function Build({ fontId }: { fontId: string }) {
  const [state, setState] = useState<BuildState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [texts, setTexts] = useState<TextCoverage[] | null>(null);
  const fail = (e: Error) => setError(e.message);

  useEffect(() => {
    api.buildState(fontId).then(setState, fail);
  }, [fontId]);
  const built = state?.report?.build;
  useEffect(() => {
    // F7: the test texts, measured with the newest build and the one before
    if (built) api.textsCoverage(fontId).then(setTexts, fail);
  }, [fontId, built]);
  useEffect(() => {
    if (!state?.job.running) return;
    const timer = window.setTimeout(() => api.buildState(fontId).then(setState, fail), 1000);
    return () => window.clearTimeout(timer);
  }, [fontId, state]);

  if (!state) return error ? <div className="error" role="alert"><span>{error}</span></div> : <p className="muted">Loading…</p>;
  const { job, coverage: c, report } = state;
  const fill = (chars: string[], filled: boolean) => api.fill(fontId, chars, filled).then(setState, fail);
  const extra = [c.generated > 0 && `${c.generated} made by the system`, c.estimated > 0 && `${c.estimated} with an estimated place`]
    .filter(Boolean).join(", ");
  const changed = report && (report.filled.join() !== c.filled.join() || report.labels?.length !== c.labels.length);
  return (
    <>
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)} aria-label="Close">×</button>
        </div>
      )}
      <div className="card">
        <p>
          From the book: <strong>{c.base}</strong> letters and <strong>{c.aksharas}</strong> aksharas
          {extra && ` (${extra})`}.
        </p>
        {c.left_out.length > 0 && <p className="muted small">Left out: {c.left_out.join(" ")}</p>}
        {c.duplicates.length > 0 && (
          <p className="muted small">
            Same label twice (the group with more copies is used): {c.duplicates.map((d) => d.label).join(" ")}
          </p>
        )}
      </div>

      <div className="card">
        <div className="row between">
          <h2>Missing ({c.missing.length})</h2>
          {c.missing.length > 0 && <button onClick={() => fill(c.missing, true)}>Fill all from normal font</button>}
        </div>
        <p className="muted small">
          The book has no letter for these. In the font they are a box, so the gap shows. Fill one from a normal
          Devanagari font (Noto Serif Devanagari); it is always marked as filled.
        </p>
        <div className="chars">
          {c.missing.map((ch) => (
            <span key={ch} className="char missing">
              <span className="char-text">{ch}</span>
              <button className="link" onClick={() => fill([ch], true)}>Fill</button>
              <button className="link" disabled title="Next phase: make it in the book's style">Generate</button>
            </span>
          ))}
        </div>
      </div>

      {c.filled.length > 0 && (
        <div className="card">
          <h2>Filled from normal font ({c.filled.length})</h2>
          <div className="chars">
            {c.filled.map((ch) => (
              <span key={ch} className="char filled">
                <span className="char-text">{ch}</span>
                <button className="link" onClick={() => fill([ch], false)}>Remove fill</button>
              </span>
            ))}
          </div>
          <label className="small">
            <input type="checkbox" checked={state.mark_filled}
                   onChange={(e) => api.changeFont(fontId, { mark_filled: e.target.checked }).then(() => api.buildState(fontId)).then(setState, fail)} />
            Mark filled characters in the font (a line under them, also in Word)
          </label>
        </div>
      )}

      <div className="card">
        <div className="row between">
          <h2>Font file</h2>
          <button className="primary" disabled={job.running} onClick={() => api.build(fontId).then(setState, fail)}>
            {report ? "Build again" : "Build font"}
          </button>
        </div>
        {job.running && (
          <>
            {job.phase === "outlines" ? "Building the font (outlines)" : "Making glyphs"}: {job.done} of {job.total || "…"}
            <progress value={job.done} max={job.total || 1} />
          </>
        )}
        {job.error && <p className="error-text">The build stopped: {job.error}</p>}
        {texts && texts.length > 0 && <TextsTable texts={texts} />}
        {report ? (
          <p>
            Build {report.build}: {report.glyphs} glyphs, {report.rules} rules,{" "}
            {report.filled.length} filled, {report.missing.length} missing.{" "}
            <a href={fontFileUrl(fontId, report.file)} download={report.file}>Download {report.file}</a>
            {changed && <span className="badge warn"> changed since this build: build again</span>}
          </p>
        ) : (
          !job.running && <p className="muted">Not built yet.</p>
        )}
      </div>
    </>
  );
}

const pct = (n: number | undefined, total: number) => (total ? `${((100 * (n ?? 0)) / total).toFixed(1)} %` : "–");

// F7: the share of each test text's aksharas the font draws as the book's own, pieced, filled or missing
function TextsTable({ texts }: { texts: TextCoverage[] }) {
  return (
    <>
      <h3>Test texts</h3>
      <table className="list">
        <thead>
          <tr>
            <th>Text</th>
            <th className="num">Aksharas</th>
            <th className="num">The book's own</th>
            <th className="num">Pieced</th>
            <th className="num">Filled</th>
            <th className="num">Missing</th>
            <th className="num">Build before</th>
          </tr>
        </thead>
        <tbody>
          {texts.map((t) => {
            const [now, before] = t.builds;
            if (!now) return null;
            return (
              <tr key={t.id}>
                <td>
                  {t.name}
                  {now.gaps && now.gaps.length > 0 && (
                    <div className="muted small">Most frequent not the book's own: {now.gaps.map(([a, n]) => `${a}×${n}`).join(" ")}</div>
                  )}
                </td>
                <td className="num">{now.aksharas}</td>
                <td className="num">{pct(now.book, now.aksharas)}</td>
                <td className="num">{pct(now.pieced, now.aksharas)}</td>
                <td className="num">{pct(now.filled, now.aksharas)}</td>
                <td className="num">{pct(now.missing, now.aksharas)}</td>
                <td className="num">{before ? `build ${before.build}: ${pct(before.book, before.aksharas)} own` : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
