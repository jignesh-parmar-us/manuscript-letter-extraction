// The letters palette of the Try it tab (F7), like the reading app's Letters palette: on-screen keys that
// type Devanagari at the cursor. Unlike the reading app's, the keys are drawn in the font being tried and
// coloured by what the font has (the book's own, pieced, filled, missing), and a second page has every
// akshara of the book as one key. Every key types the same Unicode characters as the single keys would
// (कि = क + ि), so the text is the same either way. "Keys: in the font | Unicode" only changes how the keys
// look (the font being tried, or the system's normal Devanagari font); the text box is always in the font.
import { useMemo, useState } from "react";
import { DEV, isSign, SECTIONS } from "./letters";

export type KeyKind = "book" | "pieced" | "generated" | "drawn" | "filled" | "missing";

/** What the font draws for a key's text: the book's own glyph, several of them, or a filled / missing letter. */
export function keyKind(key: string, labels: Set<string>, filled: Set<string>, made: Set<string> = new Set(),
                        drawn: Set<string> = new Set()): KeyKind {
  if (labels.has(key)) return "book";
  const chars = Array.from(key);
  if (chars.some((c) => !labels.has(c) && !filled.has(c) && !made.has(c) && !drawn.has(c))) return "missing";
  if (chars.some((c) => filled.has(c))) return "filled";
  if (chars.some((c) => made.has(c))) return "generated";
  if (chars.some((c) => drawn.has(c))) return "drawn";
  return "pieced";
}

const RECENT = "fm-recent-keys";
const LOOK = "fm-key-look";
function loadRecent(): string[] {
  try {
    return JSON.parse(window.localStorage.getItem(RECENT) ?? "[]");
  } catch {
    return [];
  }
}
function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private window: not kept
  }
}
function loadLook(): "font" | "unicode" {
  try {
    return window.localStorage.getItem(LOOK) === "unicode" ? "unicode" : "font";
  } catch {
    return "font";
  }
}

interface Props {
  family: string; // the CSS font family of the font being tried
  labels: string[]; // the book's labels in the newest build (letters and aksharas)
  filled: string[];
  generated?: string[]; // F9: signs cut from the book's aksharas
  drawn?: string[]; // F11: drawn or uploaded
  onKey: (text: string) => void;
  onBackspace: () => void; // one character
  onBackspaceAkshara: () => void; // the whole akshara before the cursor
  onHide?: () => void;
}

export default function LetterPalette(props: Props) {
  const [page, setPage] = useState<"letters" | "aksharas">("letters");
  const [recent, setRecent] = useState<string[]>(loadRecent);
  const [first, setFirst] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [look, setLook] = useState<"font" | "unicode">(loadLook);
  const keyFont = look === "font" ? { fontFamily: `"${props.family}", serif` } : undefined;
  const chooseLook = (l: "font" | "unicode") => {
    setLook(l);
    remember(LOOK, l);
  };
  const labels = useMemo(() => new Set(props.labels), [props.labels]);
  const filled = useMemo(() => new Set(props.filled), [props.filled]);
  const made = useMemo(() => new Set(props.generated ?? []), [props.generated]);
  const drawnSet = useMemo(() => new Set(props.drawn ?? []), [props.drawn]);

  const type = (k: string) => {
    props.onKey(k);
    const next = [k, ...recent.filter((r) => r !== k)].slice(0, 12);
    setRecent(next);
    remember(RECENT, JSON.stringify(next));
  };
  const key = (k: string) => {
    const kind = keyKind(k, labels, filled, made, drawnSet);
    return (
      <button key={k} className={`key fm-key ${kind}`} style={keyFont}
              onClick={() => type(k)} title={`${k}: ${KIND_TEXT[kind]}`} aria-label={k}>
        {isSign(k) ? `◌${k}` : k}
      </button>
    );
  };

  // the book's aksharas, grouped by their first letter
  const aksharas = props.labels.filter((l) => Array.from(l).length > 1);
  const groups = useMemo(() => {
    const by = new Map<string, string[]>();
    for (const a of aksharas) {
      const f = Array.from(a)[0];
      by.set(f, [...(by.get(f) ?? []), a]);
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0], "hi"));
  }, [props.labels]);
  const shown = search.trim()
    ? aksharas.filter((a) => a.includes(search.trim()))
    : first ? groups.find(([f]) => f === first)?.[1] ?? [] : [];

  return (
    <div className="palette" role="group" aria-label="Letters">
      <div className="row">
        <button className={page === "letters" ? "tab active" : "tab"} onClick={() => setPage("letters")}>Letters</button>
        <button className={page === "aksharas" ? "tab active" : "tab"} onClick={() => setPage("aksharas")}>
          Book's aksharas ({aksharas.length})
        </button>
        <button onClick={() => props.onKey(" ")} aria-label="Space">Space</button>
        <button onClick={() => props.onKey("\n")} aria-label="New line">New line</button>
        <button onClick={props.onBackspace} aria-label="Remove the character before the cursor">⌫ letter</button>
        <button onClick={props.onBackspaceAkshara} aria-label="Remove the akshara before the cursor">⌫ akshara</button>
        {props.onHide && <button className="palette-close" onClick={props.onHide}>Hide letters</button>}
      </div>
      <div className="row small">
        <span className="muted">Keys:</span>
        <button className={look === "font" ? "tab active" : "tab"} onClick={() => chooseLook("font")}
                title="The keys drawn in the font being tried">In the font</button>
        <button className={look === "unicode" ? "tab active" : "tab"} onClick={() => chooseLook("unicode")}
                title="The keys in the normal Devanagari font; the text box stays in your font">Unicode</button>
      </div>
      {recent.length > 0 && (
        <div className="palette-row">
          <span className="muted small">Used last</span>
          <div className="keys">{recent.map(key)}</div>
        </div>
      )}
      {page === "letters" &&
        SECTIONS.map((sec) => (
          <div key={sec.key} className="palette-row">
            <span className="muted small">{sec.title}</span>
            <div className="keys">{DEV[sec.key].map(key)}</div>
          </div>
        ))}
      {page === "aksharas" && (
        <>
          <div className="palette-row">
            <input placeholder="Search, e.g. क्र" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search aksharas" />
          </div>
          {!search.trim() && (
            <div className="palette-row">
              <span className="muted small">First letter</span>
              <div className="keys">
                {groups.map(([f, list]) => (
                  <button key={f} className={`key${first === f ? " selected" : ""}`} style={keyFont}
                          onClick={() => setFirst(f)} title={`${list.length} aksharas`}>
                    {f}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="palette-row">
            <div className="keys">{shown.map(key)}</div>
            {!shown.length && <span className="muted small">{search.trim() ? "None found." : "Choose a first letter."}</span>}
          </div>
        </>
      )}
      <p className="muted small">
        Keys: <span className="fm-key book">the book's own</span> · <span className="fm-key pieced">pieced</span> ·{" "}
        <span className="fm-key generated">generated</span> · <span className="fm-key drawn">drawn</span> ·{" "}
        <span className="fm-key filled">filled</span> · <span className="fm-key missing">missing</span>
      </p>
    </div>
  );
}

export const KIND_TEXT: Record<string, string> = {
  book: "the book's own",
  pieced: "pieced together from the book's glyphs",
  generated: "holds a sign Font Maker cut from the book's aksharas",
  drawn: "holds a letter you drew or uploaded",
  filled: "holds a letter filled from the normal font",
  missing: "holds a missing letter (a box)",
  other: "not Devanagari: not in this font",
};
