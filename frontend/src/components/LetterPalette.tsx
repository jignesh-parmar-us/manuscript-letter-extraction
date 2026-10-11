// The on-screen letters (consonants, conjuncts, joined letters, vowel signs, marks, digits, punctuation)
// in Gujarati or Devanagari: the label picker builds labels with it, the line truth screen corrects lines.
// A key gives its text in the palette's script; vowel signs and marks attach to the letter before them.
import { useState } from "react";

export type Script = "gujarati" | "devanagari";

export const DEV = {
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

export const SECTIONS: { key: keyof typeof DEV; title: string }[] = [
  { key: "vowels", title: "Vowels" },
  { key: "consonants", title: "Consonants" },
  { key: "conjuncts", title: "Conjuncts" },
  { key: "joined", title: "Joined letters (જોડાક્ષર): reph ર્ before a letter (ર્ક), rakar ્ર after it (ક્ર, ક્રા, bottom churn ટ્ર)" },
  { key: "signs", title: "Vowel signs, halant, marks" },
  { key: "digits", title: "Digits" },
  { key: "punctuation", title: "Punctuation" },
];

interface Props {
  onKey: (text: string) => void; // a key's text, in the palette's script
  onBackspace: () => void;
  onEmpty?: () => void;
  extra?: React.ReactNode; // more keys on the first row (a space, for a line)
  initialScript?: Script;
}

export default function LetterPalette({ onKey, onBackspace, onEmpty, extra, initialScript = "gujarati" }: Props) {
  const [script, setScript] = useState<Script>(initialScript);
  return (
    <div className="palette" role="group" aria-label="Letters">
      <div className="row">
        <span className="muted small">Palette:</span>
        <button className={script === "gujarati" ? "tab active" : "tab"} onClick={() => setScript("gujarati")}>
          ગુજરાતી
        </button>
        <button className={script === "devanagari" ? "tab active" : "tab"} onClick={() => setScript("devanagari")}>
          देवनागरी
        </button>
        {extra}
        <button onClick={onBackspace} aria-label="Remove last character">
          ⌫
        </button>
        {onEmpty && <button onClick={onEmpty}>Empty</button>}
      </div>
      {SECTIONS.map((sec) => (
        <div key={sec.key} className="palette-row">
          <span className="muted small">{sec.title}</span>
          <div className="keys">
            {DEV[sec.key].map((ch) => {
              const shown = script === "gujarati" ? toGujarati(ch) : ch;
              const isSign = sec.key === "signs" || ch.startsWith("्"); // attaches to the letter before it
              return (
                <button key={ch} className="key" onClick={() => onKey(shown)} title={shown}>
                  {isSign ? `◌${shown}` : shown}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
