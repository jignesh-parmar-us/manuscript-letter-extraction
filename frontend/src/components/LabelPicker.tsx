// Label of a group: typed in Devanagari or Gujarati (any keyboard), or built with the on-screen
// palette (consonant, halant for a conjunct, then a vowel sign, then a mark). The backend checks the
// label while it is typed (mapping.describe) and shows it in both scripts with its code points.
import { useEffect, useState } from "react";
import { api, LabelInfo } from "../api";

type Script = "gujarati" | "devanagari";

const DEV = {
  vowels: "अ आ इ ई उ ऊ ऋ ए ऐ ओ औ".split(" "),
  consonants: "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ व श ष स ह".split(" "),
  conjuncts: "क्ष त्र ज्ञ श्र".split(" "),
  signs: ["ा", "ि", "ी", "ु", "ू", "ृ", "े", "ै", "ो", "ौ", "्", "ं", "ः", "ँ", "़"],
  digits: "० १ २ ३ ४ ५ ६ ७ ८ ९".split(" "),
  punctuation: ["।", "॥", "ऽ", "ॐ"],
};

/** Devanagari -> Gujarati for the palette (same rule as mapping.py; dandas stay Devanagari). */
export function toGujarati(text: string): string {
  return Array.from(text)
    .map((ch) => {
      const cp = ch.codePointAt(0)!;
      if (ch === "।" || ch === "॥" || cp < 0x0900 || cp > 0x097f) return ch;
      return String.fromCodePoint(cp + 0x180);
    })
    .join("");
}

const SECTIONS: { key: keyof typeof DEV; title: string }[] = [
  { key: "vowels", title: "Vowels" },
  { key: "consonants", title: "Consonants" },
  { key: "conjuncts", title: "Conjuncts" },
  { key: "signs", title: "Vowel signs, halant, marks" },
  { key: "digits", title: "Digits" },
  { key: "punctuation", title: "Punctuation" },
];

interface Props {
  bookId: number;
  current: { dev: string; guj: string };
  disabled?: boolean;
  onSave: (text: string) => Promise<void>;
}

export default function LabelPicker({ bookId, current, disabled, onSave }: Props) {
  const [text, setText] = useState(current.guj);
  const [script, setScript] = useState<Script>("gujarati");
  const [info, setInfo] = useState<LabelInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => setText(current.guj), [current.guj]);

  // check the label 250 ms after the last change
  useEffect(() => {
    if (!text.trim()) {
      setInfo(null);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      api.checkLabel(text, bookId).then((r) => live && setInfo(r), () => live && setInfo(null));
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [text, bookId]);

  const add = (ch: string) => setText((t) => t + (script === "gujarati" ? toGujarati(ch) : ch));
  const backspace = () => setText((t) => Array.from(t).slice(0, -1).join(""));

  async function save(value: string) {
    setSaving(true);
    try {
      await onSave(value);
    } finally {
      setSaving(false);
    }
  }

  const unchanged = info?.ok && info.devanagari === current.dev;

  return (
    <div className="label-picker">
      <div className="row">
        <input
          className="label-input"
          aria-label="Label"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type in ગુજરાતી or देवनागरी"
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === "Enter" && info?.ok && !unchanged) save(text);
          }}
        />
        <button className="primary" disabled={disabled || saving || !info?.ok || unchanged} onClick={() => save(text)}>
          Save label
        </button>
        {current.dev && (
          <button disabled={disabled || saving} onClick={() => save("")}>
            Clear label
          </button>
        )}
        <button className="link" onClick={() => setOpen((o) => !o)} disabled={disabled}>
          {open ? "Hide letters" : "Letters…"}
        </button>
      </div>
      <div className="label-check small" aria-live="polite">
        {info?.ok && (
          <span>
            <span className="big-letter">{info.gujarati}</span> <span className="big-letter">{info.devanagari}</span>{" "}
            <span className="muted">
              {info.category} · {info.code_points_gujarati}
              {info.kept_in_devanagari && info.kept_in_devanagari.length > 0 &&
                ` · kept in Devanagari: ${info.kept_in_devanagari.join(" ")}`}
            </span>
          </span>
        )}
        {info && !info.ok && <span className="error-text">{info.error}</span>}
      </div>
      {open && (
        <div className="palette">
          <div className="row">
            <span className="muted small">Palette:</span>
            <button className={script === "gujarati" ? "tab active" : "tab"} onClick={() => setScript("gujarati")}>
              ગુજરાતી
            </button>
            <button className={script === "devanagari" ? "tab active" : "tab"} onClick={() => setScript("devanagari")}>
              देवनागरी
            </button>
            <button onClick={backspace} aria-label="Remove last character">
              ⌫
            </button>
            <button onClick={() => setText("")}>Empty</button>
          </div>
          {SECTIONS.map((sec) => (
            <div key={sec.key} className="palette-row">
              <span className="muted small">{sec.title}</span>
              <div className="keys">
                {DEV[sec.key].map((ch) => {
                  const shown = script === "gujarati" ? toGujarati(ch) : ch;
                  const isSign = sec.key === "signs";
                  return (
                    <button key={ch} className="key" onClick={() => add(ch)} title={shown}>
                      {isSign ? `◌${shown}` : shown}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
