// The script tabs of the text views (ગુજરાતી / देवनागरी) and the library's own fonts beside them (custom fonts,
// T2; docs/CUSTOM_FONT_PLAN.md). + adds a font: a .ttf / .otf uploaded, or one built in Font Maker (picked from a
// list, so not every Font Maker font becomes a tab). A font tab shows the text in that font, in the script the
// font has (a font with both keeps the script last chosen); its downloads (PDF, picture, Word) use it. Characters
// of the shown text that the font lacks are counted on its tab and highlighted in the text.
// Fonts draw their letters at different sizes within the same font size: a custom font is scaled so that its
// letters are as tall as those of the normal fonts (measured on a few letters, FontFace size-adjust); the
// screen, the PDF and the pictures use the scaled font, and Word files get the same scale on their font size.
// A− / A+ on the chosen font's tab change its size from there in steps of 5% (kept with the font in the library).
import { useEffect, useRef, useState } from "react";
import { api, DisplayFont, FontMakerFont } from "../api";

export type Script = "gujarati" | "devanagari";

/** The text's normal fonts (also the fallback of a custom font for the characters it lacks). */
export const DEFAULT_FONT = `"Noto Sans Gujarati", "Gujarati Sangam MN", "Shruti", "Noto Sans Devanagari", sans-serif`;

const measured = new Map<string, Promise<number>>(); // font id-version -> its matched scale
const faces = new Map<string, Promise<void>>();       // face name -> loaded

/** The face of a font at a scale (each scale is a face of its own: size-adjust is fixed when it is loaded). */
function faceName(f: DisplayFont, scale: number): string {
  return `display-font-${f.id}-${f.version}-${Math.round(scale * 100)}`;
}

const STEP = 0.05;
const MIN_SIZE = 0.5;
const MAX_SIZE = 2;

/** Letters to compare a font's size on, per script. */
const PROBE: Record<Script, string> = { gujarati: "કગમનરસ", devanagari: "कगमनरस" };

/** How tall the letters of `probe` are in `font` (CSS font-family) at 100px, or 0 when it cannot be measured. */
function inkHeight(font: string, probe: string): number {
  try {
    const ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return 0;
    ctx.font = `100px ${font}`;
    const m = ctx.measureText(probe);
    return (m.actualBoundingBoxAscent ?? 0) + (m.actualBoundingBoxDescent ?? 0);
  } catch {
    return 0; // no canvas (tests)
  }
}

/** The scale that makes `face`'s letters as tall as the normal fonts' (1 when it cannot be measured),
 *  kept between 0.7 and 1.6 so a font with odd measures is not blown up. */
export function matchScale(face: string, script: Script): number {
  const own = inkHeight(`"${face}"`, PROBE[script]);
  const normal = inkHeight(DEFAULT_FONT, PROBE[script]);
  if (!own || !normal) return 1;
  return Math.round(Math.min(1.6, Math.max(0.7, normal / own)) * 100) / 100;
}

/** The scale that matches a font's letters to the normal fonts' (measured once per font file). */
function measure(f: DisplayFont): Promise<number> {
  const key = `${f.id}-${f.version}`;
  let got = measured.get(key);
  if (!got) {
    if (typeof FontFace === "undefined" || !document.fonts) got = Promise.resolve(1);   // tests (no fonts)
    else {
      const name = `display-font-${key}-probe`;
      got = (async () => {
        const probe = await new FontFace(name, `url("${api.fontUrl(f.id, f.version)}")`).load();   // unscaled
        document.fonts.add(probe);
        const scale = matchScale(name, f.scripts[0]);
        document.fonts.delete(probe);
        return scale;
      })();
      got.catch(() => measured.delete(key)); // try again next time
    }
    measured.set(key, got);
  }
  return got;
}

/** Load a font into the page (FontFace), at its matched scale times your size; gives the face's name and scale
 *  when it can be drawn. */
async function loadFace(f: DisplayFont): Promise<{ name: string; scale: number }> {
  const scale = Math.round((await measure(f)) * (f.size || 1) * 100) / 100;
  const name = faceName(f, scale);
  let got = faces.get(name);
  if (!got) {
    if (typeof FontFace === "undefined" || !document.fonts) got = Promise.resolve();
    else {
      got = new FontFace(name, `url("${api.fontUrl(f.id, f.version)}")`,
        { sizeAdjust: `${Math.round(scale * 100)}%` } as FontFaceDescriptors).load().then((face) => {
        document.fonts.add(face);
      });
      got.catch(() => faces.delete(name));
    }
    faces.set(name, got);
  }
  await got;
  return { name, scale };
}

function storedFont(): string | null {
  try {
    return localStorage.getItem("text-font");
  } catch {
    return null;
  }
}

function rememberFont(id: string | null) {
  try {
    if (id) localStorage.setItem("text-font", id);
    else localStorage.removeItem("text-font");
  } catch {
    // a private window: the choice lasts until the page is closed
  }
}

/** The characters of `texts` (Devanagari and Gujarati blocks) that `font` lacks, in order of first use. */
export function missingChars(texts: string[], font: DisplayFont | null): string[] {
  if (!font) return [];
  const have = new Set(Array.from(font.chars));
  const out = new Set<string>();
  for (const t of texts)
    for (const c of t) {
      const code = c.codePointAt(0) ?? 0;
      if (code >= 0x0900 && code <= 0x0aff && !have.has(c)) out.add(c);
    }
  return [...out];
}

export interface TextFont {
  fonts: DisplayFont[];
  script: Script;          // the script shown (a font tab: one the font has)
  font: DisplayFont | null; // the chosen font, or null for the normal fonts
  family: string;          // CSS font-family of the text
  scale: number;           // the chosen font's size against the normal fonts' (for Word files); 1 without one
  chooseScript: (s: Script) => void;
  chooseFont: (f: DisplayFont) => void;
  setFonts: (fonts: DisplayFont[]) => void;
  /** A− / A+: the chosen font a step smaller (-1) or larger (+1); 0: back to the matched size. */
  resize: (step: -1 | 0 | 1) => void;
  /** Resolves when the chosen font can be drawn (for the picture). */
  ready: () => Promise<void>;
  /** Whether the chosen font lacks a character of `s`. */
  lacks: (s: string) => boolean;
}

/** The chosen script and font of a text view, the font remembered in the browser. */
export function useTextFont(onError: (e: unknown) => void): TextFont {
  const [fonts, setFonts] = useState<DisplayFont[]>([]);
  const [scriptChoice, setScript] = useState<Script>("gujarati");
  const [fontId, setFontId] = useState<string | null>(storedFont);
  useEffect(() => {
    api.fonts().then(setFonts, () => setFonts([])); // no list: no font tabs, the script tabs still work
  }, []);
  const font = fonts.find((f) => f.id === fontId) ?? null;
  const script: Script = font && !font.scripts.includes(scriptChoice) ? font.scripts[0] : scriptChoice;
  // the loaded face of the chosen font at its size (until then, the normal fonts)
  const [face, setFace] = useState<{ key: string; name: string; scale: number } | null>(null);
  const key = font ? `${font.id}-${font.version}-${font.size}` : "";
  useEffect(() => {
    if (!font) return;
    let live = true;
    loadFace(font).then((got) => live && setFace({ key, ...got }),
      () => onError(new Error(`The font "${font.name}" could not be loaded.`)));
    return () => {
      live = false;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const shownFace = font && face?.key === key ? face : null;
  const have = font ? new Set(Array.from(font.chars)) : null;
  return {
    fonts,
    script,
    font,
    family: shownFace ? `"${shownFace.name}", ${DEFAULT_FONT}` : DEFAULT_FONT,
    scale: shownFace?.scale ?? 1,
    chooseScript: (s) => {
      setScript(s);
      setFontId(null);
      rememberFont(null);
    },
    chooseFont: (f) => {
      if (!f.scripts.includes(scriptChoice)) setScript(f.scripts[0]);
      setFontId(f.id);
      rememberFont(f.id);
    },
    setFonts,
    resize: (step) => {
      if (!font) return;
      const size = step === 0 ? 1 : Math.round(Math.min(MAX_SIZE, Math.max(MIN_SIZE, font.size + step * STEP)) * 100) / 100;
      if (size === font.size) return;
      setFonts(fonts.map((f) => (f.id === font.id ? { ...f, size } : f)));   // at once; kept in the library
      api.setFontSize(font.id, size).catch(onError);
    },
    ready: () => (font ? loadFace(font).then(() => undefined) : Promise.resolve()),
    lacks: (s) => {
      if (!have) return false;
      for (const c of s) {
        const code = c.codePointAt(0) ?? 0;
        if (code >= 0x0900 && code <= 0x0aff && !have.has(c)) return true;
      }
      return false;
    },
  };
}

const SCRIPT_NAMES: Record<Script, string> = { gujarati: "Gujarati", devanagari: "Devanagari" };

/** ગુજરાતી | देवनागरी | a tab per font (✕ removes it) | + (upload, or from Font Maker). `shown`: the text on the
 *  screen, for the missing characters of the chosen font. */
export default function ScriptTabs({ tf, shown, onError }: { tf: TextFont; shown: string[]; onError: (e: unknown) => void }) {
  const [menu, setMenu] = useState(false);
  const [fontMaker, setFontMaker] = useState<FontMakerFont[] | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const missing = missingChars(shown, tf.font);

  async function upload(f: File) {
    setBusy(true);
    try {
      const got = await api.uploadFont(f);
      tf.setFonts(await api.fonts());
      tf.chooseFont(got);
      setMenu(false);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  async function addFromFontMaker(project: string) {
    setBusy(true);
    try {
      const got = await api.addFontMakerFont(project);
      tf.setFonts(await api.fonts());
      tf.chooseFont(got);
      setMenu(false);
      setFontMaker(null);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }
  async function remove(f: DisplayFont) {
    const what = f.source === "fontmaker" ? "Its Font Maker font is not changed." : "The uploaded file is deleted.";
    if (!window.confirm(`Remove the font "${f.name}" from the tabs of every book? ${what}`)) return;
    try {
      await api.removeFont(f.id);
      if (tf.font?.id === f.id) tf.chooseScript(tf.script);
      tf.setFonts(tf.fonts.filter((x) => x.id !== f.id));
    } catch (e) {
      onError(e);
    }
  }

  return (
    <div className="row script-tabs" role="group" aria-label="Script">
      <button className={!tf.font && tf.script === "gujarati" ? "tab active" : "tab"} onClick={() => tf.chooseScript("gujarati")}>
        ગુજરાતી
      </button>
      <button className={!tf.font && tf.script === "devanagari" ? "tab active" : "tab"} onClick={() => tf.chooseScript("devanagari")}>
        देवनागरी
      </button>
      {tf.fonts.map((f) => {
        const on = tf.font?.id === f.id;
        return (
          <span key={f.id} className={`font-tab${on ? " active" : ""}`}>
            <button className={on ? "tab active" : "tab"} onClick={() => tf.chooseFont(f)}
              title={`The text in ${f.name} (${f.scripts.map((s) => SCRIPT_NAMES[s]).join(", ")}${f.source === "fontmaker" ? ", from Font Maker" : ""}). ${
                f.embeddable ? "Word files embed it." : "Word files name it; it shows only where the font is installed."}${
                f.joins ? "" : " It has only Apple's rules for joining letters: conjuncts may not join in Word on Windows or in other browsers."}`}>
              {f.name}
              {on && missing.length > 0 && (
                <span className="font-missing" title={`This font lacks ${missing.join(" ")}: shown in the normal font, highlighted`}>
                  {" "}⚠ {missing.length} missing
                </span>
              )}
            </button>
            {on && (
              <span className="font-size" role="group" aria-label="Font size">
                <button className="link" aria-label="Smaller font" title="A step (5%) smaller" disabled={f.size <= MIN_SIZE}
                  onClick={() => tf.resize(-1)}>
                  A−
                </button>
                {f.size !== 1 && (
                  <button className="link small" title="Your size against the matched size: click to go back to the matched size"
                    onClick={() => tf.resize(0)}>
                    {Math.round(f.size * 100)}%
                  </button>
                )}
                <button className="link" aria-label="Larger font" title="A step (5%) larger" disabled={f.size >= MAX_SIZE}
                  onClick={() => tf.resize(1)}>
                  A+
                </button>
              </span>
            )}
            <button className="link font-remove" aria-label={`Remove the font ${f.name}`} title="Remove this font" onClick={() => remove(f)}>
              ✕
            </button>
          </span>
        );
      })}
      <span className="font-add">
        <button className="tab" aria-label="Add a font" aria-expanded={menu} title="Show the text in a font of your own"
          onClick={() => {
            setMenu((v) => !v);
            setFontMaker(null);
          }}>
          +
        </button>
        {menu && (
          <div className="card font-menu" aria-label="Add a font">
            <button disabled={busy} onClick={() => file.current?.click()}>
              Upload a font file (.ttf, .otf, .ttc)…
            </button>
            <button disabled={busy} onClick={() => api.fontMakerFonts().then(setFontMaker, onError)}>
              From Font Maker…
            </button>
            {fontMaker && (
              fontMaker.length === 0 ? (
                <p className="small muted">No Font Maker font is built yet.</p>
              ) : (
                <ul className="font-maker-list">
                  {fontMaker.map((m) => (
                    <li key={m.project}>
                      <button className="link" disabled={busy || m.added} onClick={() => addFromFontMaker(m.project)}>
                        {m.name}
                      </button>
                      <span className="small muted"> {m.added ? "(a tab already)" : `built ${new Date(m.built_at).toLocaleDateString()}`}</span>
                    </li>
                  ))}
                </ul>
              )
            )}
            <p className="small muted">
              Unicode fonts only. Old-style fonts (Shree-Lipi, Terafont, Kruti Dev, …) are not supported yet.
            </p>
          </div>
        )}
        <input ref={file} type="file" accept=".ttf,.otf,.ttc" hidden aria-label="Font file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) upload(f);
          }} />
      </span>
    </div>
  );
}
