// Label of a group: typed in Devanagari or Gujarati (any keyboard), or built with the on-screen
// palette (consonant, halant for a conjunct, then a vowel sign, then a mark). The backend checks the
// label while it is typed (mapping.describe) and shows it in both scripts with its code points.
// A label can be one letter or a word (several letters). One label belongs to one group: if another
// group has it, the picker offers "Merge into" that group (onMerge) instead of saving, or, for samples
// (no onMerge), says which group they will go into.
import { useEffect, useRef, useState } from "react";
import { api, LabelInfo, LabelUser } from "../api";

type Script = "gujarati" | "devanagari";

const DEV = {
  vowels: "अ आ इ ई उ ऊ ऋ ए ऐ ओ औ".split(" "),
  consonants: "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ व श ष स ह".split(" "),
  conjuncts: "क्ष त्र ज्ञ श्र".split(" "),
  // joined letters: reph र् goes before a letter (र्क), rakar ्र after it (क्र, क्रा; on ट and ड it is
  // drawn as the bottom churn, ट्र)
  joined: ["र्", "्र"],
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
  { key: "joined", title: "Joined letters (જોડાક્ષર): reph ર્ before a letter (ર્ક), rakar ્ર after it (ક્ર, ક્રા, bottom churn ટ્ર)" },
  { key: "signs", title: "Vowel signs, halant, marks" },
  { key: "digits", title: "Digits" },
  { key: "punctuation", title: "Punctuation" },
];

interface Props {
  bookId: number;
  current: { dev: string; guj: string };
  initialText?: string; // text to start with instead of the current label (a suggestion to change)
  disabled?: boolean;
  onSave: (text: string) => Promise<boolean | void>; // false: not saved (the letters stay open)
  saveText?: string; // the save button's text (default "Save label")
  canClear?: boolean; // offer "Clear label" when there is a label (default true)
  groupId?: number; // the group being labelled (not counted as "another group with this label")
  onMerge?: (target: LabelUser) => Promise<boolean | void>; // merge the group into the one that has the label
}

export default function LabelPicker(props: Props) {
  const { bookId, current, disabled, onSave, saveText = "Save label", canClear = true, groupId, onMerge } = props;
  const [text, setText] = useState(props.initialText ?? current.guj);
  const [script, setScript] = useState<Script>("gujarati");
  const [info, setInfo] = useState<LabelInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  // a new label (saved, undone) replaces the text; not on the first render, which may start from initialText
  const shownLabel = useRef(current.guj);
  useEffect(() => {
    if (shownLabel.current === current.guj) return;
    shownLabel.current = current.guj;
    setText(current.guj);
  }, [current.guj]);

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
  }, [text, bookId, current.dev]); // also after a save: which groups have the label changed

  const add = (ch: string) => setText((t) => t + (script === "gujarati" ? toGujarati(ch) : ch));
  const backspace = () => setText((t) => Array.from(t).slice(0, -1).join(""));

  async function save(value: string) {
    setSaving(true);
    try {
      if ((await onSave(value)) !== false) setOpen(false); // saved: hide the letters
    } finally {
      setSaving(false);
    }
  }

  const unchanged = info?.ok && info.devanagari === current.dev;
  const others = (info?.ok && info.used_by?.filter((g) => g.id !== groupId)) || [];
  const free = others.filter((g) => !g.locked).sort((a, b) => b.samples - a.samples);
  // a group cannot take a label another group has; samples can only go into an unlocked group
  const blocked = onMerge ? others.length > 0 : others.length > 0 && free.length === 0;
  const canSave = !disabled && !saving && info?.ok && !unchanged && !blocked;

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
            if (e.key === "Enter" && canSave) save(text);
          }}
        />
        <button className="primary" disabled={!canSave} onClick={() => save(text)}>
          {saveText}
        </button>
        {canClear && current.dev && (
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
              {info.category}
              {info.letters && info.letters > 1 ? ` (${info.letters} letters)` : ""} · {info.code_points_gujarati}
              {info.kept_in_devanagari && info.kept_in_devanagari.length > 0 &&
                ` · kept in Devanagari: ${info.kept_in_devanagari.join(" ")}`}
            </span>
          </span>
        )}
        {info && !info.ok && <span className="error-text">{info.error}</span>}
      </div>
      {others.length > 0 && (
        <div className="label-used row small" role="status">
          {onMerge ? (
            <>
              <span className="error-text">
                {info?.gujarati} is already the label of {others.map((g) => `${g.code} (${g.samples})`).join(", ")}.
                One label belongs to one group:
              </span>
              {others.map((g) => (
                <button
                  key={g.id}
                  disabled={disabled || saving || g.locked}
                  title={g.locked ? `${g.code} is locked; unlock it first` : undefined}
                  onClick={async () => {
                    setSaving(true);
                    try {
                      if ((await onMerge(g)) !== false) setOpen(false);
                    } finally {
                      setSaving(false);
                    }
                  }}
                >
                  Merge into {g.code}
                  {g.locked ? " (locked)" : ""}
                </button>
              ))}
            </>
          ) : free.length > 0 ? (
            <span className="muted">
              → into the group {free[0].code} ({free[0].samples} samples)
            </span>
          ) : (
            <span className="error-text">
              The group {others[0].code} with this label is locked; unlock it first.
            </span>
          )}
        </div>
      )}
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
                  const isSign = sec.key === "signs" || ch.startsWith("्"); // attaches to the letter before it
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
