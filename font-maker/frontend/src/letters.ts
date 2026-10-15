// The keys of the letters palette (F7), and akshara splitting for "⌫ akshara".
//
// The key lists are a COPY of the reading app's (frontend/src/components/LetterPalette.tsx, `DEV`): the two
// screens share no code (font-maker/docs/FONT_PLAN.md, section 1). Keep them in step; letters.test.ts checks
// that every key of the reading app is here. Devanagari only (FONT_PLAN_PHASE2.md, F7).

export const DEV = {
  vowels: "अ आ इ ई उ ऊ ऋ ए ऐ ओ औ".split(" "),
  consonants: "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ व श ष स ह".split(" "),
  conjuncts: "क्ष त्र ज्ञ श्र".split(" "),
  // joined letters: reph र् goes before a letter (र्क), rakar ्र after it (क्र, क्रा)
  joined: ["र्", "्र"],
  signs: ["ा", "ि", "ी", "ु", "ू", "ृ", "े", "ै", "ो", "ौ", "्", "ं", "ः", "ँ", "़"],
  digits: "० १ २ ३ ४ ५ ६ ७ ८ ९".split(" "),
  punctuation: ["।", "॥", "ऽ", "ॐ"],
};

export const SECTIONS: { key: keyof typeof DEV; title: string }[] = [
  { key: "vowels", title: "Vowels" },
  { key: "consonants", title: "Consonants" },
  { key: "conjuncts", title: "Conjuncts" },
  { key: "joined", title: "Joined letters: reph र् before a letter (र्क), rakar ्र after it (क्र)" },
  { key: "signs", title: "Vowel signs, halant, marks" },
  { key: "digits", title: "Digits" },
  { key: "punctuation", title: "Punctuation" },
];

/** A key that attaches to the letter before it: shown on a dotted circle. */
export const isSign = (key: string) => DEV.signs.includes(key) || key.startsWith("्");

// ---- akshara splitting (as letter_extractor/ocr/aksharas.py split_spans) ----------------------------------
const inRange = (c: number, a: number, b: number) => c >= a && c <= b;

function kindOf(ch: string): string {
  const c = ch.codePointAt(0)!;
  if (inRange(c, 0x0915, 0x0939) || inRange(c, 0x0958, 0x095f) || inRange(c, 0x0978, 0x097f)) return "consonant";
  if (inRange(c, 0x0904, 0x0914) || c === 0x0960 || c === 0x0961 || inRange(c, 0x0972, 0x0977)) return "vowel";
  if (inRange(c, 0x093a, 0x093b) || inRange(c, 0x093e, 0x094c) || inRange(c, 0x094e, 0x094f) ||
      inRange(c, 0x0955, 0x0957) || c === 0x0962 || c === 0x0963) return "sign";
  if (inRange(c, 0x0900, 0x0903) || inRange(c, 0x0951, 0x0954)) return "mark";
  if (c === 0x094d) return "virama";
  if (c === 0x093c) return "nukta";
  if (c === 0x200c || c === 0x200d) return "joiner";
  if (/\s/.test(ch)) return "space";
  return "other";
}

/** [start, end) of each akshara (spaces skipped); Devanagari is in the BMP, so indexes are code units. */
export function splitSpans(text: string): [number, number][] {
  const spans: [number, number][] = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    const k = kindOf(text[i]);
    if (k === "space") {
      i += 1;
      continue;
    }
    const start = i;
    if (k === "consonant") {
      i += 1;
      while (i < n) {
        const k2 = kindOf(text[i]);
        if (k2 === "nukta" || k2 === "joiner") i += 1;
        else if (k2 === "virama") {
          i += 1;
          while (i < n && kindOf(text[i]) === "joiner") i += 1;
          if (i < n && kindOf(text[i]) === "consonant") i += 1;
          else break;
        } else break;
      }
      while (i < n && ["sign", "mark", "nukta"].includes(kindOf(text[i]))) i += 1;
    } else if (k === "vowel" || text[i] === "ॐ") {
      i += 1;
      while (i < n && ["sign", "mark"].includes(kindOf(text[i]))) i += 1;
    } else if (["sign", "mark", "virama", "nukta", "joiner"].includes(k)) {
      i += 1;
      while (i < n && ["sign", "mark"].includes(kindOf(text[i]))) i += 1;
    } else {
      i += 1;
    }
    spans.push([start, i]);
  }
  return spans;
}

/** Where "⌫ akshara" starts removing, for a cursor at `pos`: the start of the akshara before it. */
export function aksharaStartBefore(text: string, pos: number): number {
  if (pos <= 0) return 0;
  if (kindOf(text[pos - 1]) === "space") return pos - 1;
  const span = splitSpans(text.slice(0, pos)).pop();
  return span ? span[0] : pos - 1;
}
