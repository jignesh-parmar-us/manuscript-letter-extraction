// The Glyphs tab (F2): every glyph of the font (Devanagari label first: the font is Devanagari only), made from its group's best copies. Click one to pick a copy
// yourself, go back to the system pick, or leave the group out. Your choices never change the group.
// Opening the tab brings the glyphs up to date: only glyphs whose group changed are made again.
import { useEffect, useState } from "react";
import { api, Copy, copyUrl, Glyph, GlyphState, glyphUrl, Choice, Metrics } from "./api";

type Filter = "all" | "pick" | "copy" | "generated" | "estimated" | "left_out" | "auto" | "lost";
const FILTERS: [Filter, string, (g: Glyph) => boolean][] = [
  ["all", "All", () => true],
  ["pick", "Your picks", (g) => g.method === "pick"],
  ["copy", "Copies disagree (one copy used)", (g) => g.method === "copy" && g.count > 1],
  ["generated", "Made by the system", (g) => g.generated],
  ["estimated", "Place estimated", (g) => g.placed === "estimated"],
  ["left_out", "Left out", (g) => g.left_out],
  ["auto", "Not reviewed", (g) => g.status === "auto"],
  ["lost", "Your pick was lost", (g) => g.lost],
];

export function methodText(g: Glyph): string {
  if (g.method === "pick") return "your pick";
  if (g.method === "average") return `average of ${g.used.length}`;
  return g.count > 1 ? "one copy (copies disagree)" : "one copy";
}

// Where a glyph sits, in words (page pixels; + = below the baseline).
export function placeText(g: Glyph): string {
  if (g.bottom === null || g.top === null) return "no place yet";
  const b = Math.round(g.bottom);
  const where = b === 0 ? "on the line" : b > 0 ? `${b} px below the line` : `${-b} px above the line`;
  return `${where}, ${Math.round(g.bottom - g.top)} px tall, ${Math.round(g.width ?? 0)} px wide` +
    (g.placed === "estimated" ? " (estimated: no copy on a page line)" : "");
}

function MetricsLine({ m }: { m: Metrics }) {
  if (!m.lines) return null;
  const px = (v: number | null | undefined) => (v === null || v === undefined ? "?" : `${Math.round(v)} px`);
  return (
    <p className="muted small">
      Measured on {m.lines} lines: line height {px(m.line_height)}, letters {px(m.letter_gap)} apart, word space{" "}
      {px(m.word_space)}.
    </p>
  );
}

// The glyphs set on one baseline, at their measured places, to check heights by eye.
const ZOOM = 0.7;
function LineView({ fontId, glyphs }: { fontId: string; glyphs: Glyph[] }) {
  const placed = glyphs.filter((g) => g.bottom !== null && g.top !== null);
  const above = Math.max(0, ...placed.map((g) => -(g.top as number)));
  const below = Math.max(0, ...placed.map((g) => g.bottom as number));
  return (
    <div className="line-view">
      {placed.map((g) => (
        <div key={g.group} className="on-line" title={`${g.label_dev}: ${placeText(g)}`}
             style={{ width: (g.width ?? 0) * ZOOM, height: (above + below) * ZOOM }}>
          <span className="baseline" style={{ top: above * ZOOM }} />
          <img src={glyphUrl(fontId, g)} alt={g.label_dev} loading="lazy"
               style={{ top: (above + (g.top as number)) * ZOOM, height: ((g.bottom as number) - (g.top as number)) * ZOOM }} />
        </div>
      ))}
    </div>
  );
}

export default function Glyphs({ fontId }: { fontId: string }) {
  const [state, setState] = useState<GlyphState | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<"grid" | "line">("grid");
  const [open, setOpen] = useState<Glyph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.checkGlyphs(fontId).then(setState, (e: Error) => setError(e.message));
  }, [fontId]);
  useEffect(() => {
    // while the glyphs are being made, ask for the progress once a second
    if (!state?.job.running) return;
    const timer = window.setTimeout(() => api.glyphs(fontId).then(setState, (e: Error) => setError(e.message)), 1000);
    return () => window.clearTimeout(timer);
  }, [fontId, state]);

  const choose = (g: { group: number }, choice: Choice, sample?: number) =>
    api.choose(fontId, g.group, choice, sample).then((out) => {
      setState((s) => s && {
        ...s,
        lost: out.lost,
        glyphs: out.glyph ? s.glyphs.map((x) => (x.group === g.group ? out.glyph! : x)) : s.glyphs,
      });
      setOpen((o) => (o && out.glyph && o.group === g.group ? out.glyph : null));
    }, (e: Error) => setError(e.message));

  if (!state) return error ? <div className="error" role="alert"><span>{error}</span></div> : <p className="muted">Loading…</p>;
  const job = state.job;
  const shown = state.glyphs.filter(FILTERS.find(([f]) => f === filter)![2]);
  return (
    <>
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)} aria-label="Close">×</button>
        </div>
      )}
      {job.running && (
        <div className="card">
          Making glyphs: {job.done} of {job.total || "…"}
          <progress value={job.done} max={job.total || 1} />
        </div>
      )}
      {job.error && <p className="error-text">Making the glyphs stopped: {job.error}</p>}
      {state.lost.length > 0 && (
        <div className="card">
          <strong>Your pick was lost</strong> for {state.lost.length} {state.lost.length === 1 ? "group" : "groups"}: the
          group changed in the reading app, so the system pick is used again. Choose again, or forget the pick.
          <ul>
            {state.lost.map((p) => (
              <li key={p.group}>
                {p.label} ({p.reason}){" "}
                <button className="link" onClick={() => choose(p, "system")}>Forget</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <MetricsLine m={state.metrics ?? {}} />
      <div className="row toolbar">
        {FILTERS.map(([f, text, test]) => (
          <button key={f} className={f === filter ? "primary" : ""} onClick={() => setFilter(f)}>
            {text} ({state.glyphs.filter(test).length})
          </button>
        ))}
      </div>
      <div className="row toolbar">
        <button className={`tab${view === "grid" ? " active" : ""}`} onClick={() => setView("grid")}>Grid</button>
        <button className={`tab${view === "line" ? " active" : ""}`} onClick={() => setView("line")}>On the line</button>
      </div>
      {view === "line" && <LineView fontId={fontId} glyphs={shown} />}
      {view === "grid" && <div className="grid">
        {shown.map((g) => (
          <button key={g.group} className={`tile glyph${g.left_out ? " left-out" : ""}${g.lost ? " lost" : ""}`}
                  onClick={() => setOpen(g)} title={`${g.label_dev} ${g.label_guj}: ${methodText(g)}`}>
            <img src={glyphUrl(fontId, g)} alt={g.label_dev} loading="lazy" />
            <span className="glyph-label">
              {g.label_dev} <span className="muted">{g.label_guj}</span>
            </span>
            {g.method === "pick" && <span className="badge ok">pick</span>}
            {g.generated && <span className="badge warn">made by the system</span>}
            {g.status === "auto" && <span className="badge warn">not reviewed</span>}
            {g.left_out && <span className="badge warn">left out</span>}
          </button>
        ))}
      </div>}
      {state.cut_errors.length > 0 && (
        <p className="muted small">
          Not made, because the label holds more than one akshara (a cut to fix in the reading app):{" "}
          {state.cut_errors.map((c) => c.label_dev).join(", ")}.
        </p>
      )}
      {open && <GlyphDialog fontId={fontId} glyph={open} onChoose={choose} onClose={() => setOpen(null)} />}
    </>
  );
}

function GlyphDialog(props: { fontId: string; glyph: Glyph; onChoose: (g: Glyph, c: Choice, s?: number) => void; onClose: () => void }) {
  const g = props.glyph;
  const [copies, setCopies] = useState<Copy[] | null>(null);
  const [outline, setOutline] = useState<{ d: string; size: [number, number] } | null>(null);
  useEffect(() => {
    api.copies(props.fontId, g.group).then(setCopies, () => setCopies([]));
  }, [props.fontId, g.group]);
  useEffect(() => {
    // the outline the font will get (F4), traced the first time it is asked for
    setOutline(null);
    api.outline(props.fontId, g.group).then(setOutline, () => setOutline(null));
  }, [props.fontId, g.group, g.image]);
  return (
    <div className="backdrop" onClick={props.onClose}>
      <div className="dialog glyph-dialog" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <h2>
            {g.label_dev} <span className="muted">{g.label_guj}</span>
          </h2>
          <button className="link" onClick={props.onClose} aria-label="Close">×</button>
        </div>
        <div className="row">
          <img className="glyph-big" src={glyphUrl(props.fontId, g)} alt={g.label_dev} />
          {outline && (
            // filled like a font fills it: a hole running the wrong way would show up filled
            <svg className="glyph-big" viewBox={`0 0 ${outline.size[0]} ${outline.size[1]}`}
                 style={{ aspectRatio: `${outline.size[0]} / ${outline.size[1]}` }} role="img">
              <title>Outline</title>
              <path d={outline.d} fillRule="nonzero" />
            </svg>
          )}
          <div>
            <p>
              {methodText(g)}
              {g.lost && <span className="badge warn"> your pick was lost</span>}
              {g.generated && <span className="badge warn"> made by the system</span>}
            </p>
            <p className="muted small">{placeText(g)}.</p>
            <p className="muted small">
              {g.count} copies in the group{g.count > 1 ? `; they agree ${Math.round(g.agree * 100)}%` : ""}.
            </p>
            <div className="row">
              {g.method === "pick" && <button onClick={() => props.onChoose(g, "system")}>Use the system pick</button>}
              {g.left_out ? (
                <button onClick={() => props.onChoose(g, "keep")}>Use in the font again</button>
              ) : (
                <button className="danger" onClick={() => props.onChoose(g, "left_out")}>Leave out of the font</button>
              )}
            </div>
          </div>
        </div>
        <p className="muted small">Click a copy to use it instead (best first):</p>
        <div className="grid copies">
          {copies === null && <span className="muted">Loading…</span>}
          {copies?.map((c) => (
            <button key={c.id} className={`tile${g.method === "pick" && g.used[0] === c.id ? " selected" : ""}`}
                    onClick={() => props.onChoose(g, "copy", c.id)} aria-label={`Use copy ${c.id}`}>
              <img src={copyUrl(c)} alt="" loading="lazy" />
              {c.generated && <span className="badge warn">system</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
