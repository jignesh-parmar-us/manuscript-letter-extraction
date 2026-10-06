// "Letter overview" in the Review tab: every consonant with every vowel sign (and the vowels), and
// which of them have no labelled group yet. A letter with a labelled group links to it; a letter
// that no group has as its label but some group is suggested as, links to that group to review.
// Labels are matched exactly (Devanagari, as stored); a word label does not count for its letters.
// Below the table, every labelled group whose label is not in it (words, conjuncts, letters with
// a mark, dandas, digits), so the page shows every label of the book.
import { useMemo, useState } from "react";
import { Group } from "../api";
import { toGujarati } from "../components/LabelPicker";
import { go } from "../route";
import { ReviewContext } from "./Review";

export const CONSONANTS = "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल ळ व श ष स ह".split(" ");
export const CONJUNCTS = "क्ष त्र ज्ञ श्र".split(" ");
// columns: the consonant alone, then each vowel sign
export const SIGNS = ["", "ा", "ि", "ी", "ु", "ू", "ृ", "े", "ै", "ो", "ौ"];
// the vowels in the same columns: अ alone, आ with ा, इ with ि, ...
export const VOWELS = "अ आ इ ई उ ऊ ऋ ए ऐ ओ औ".split(" ");

type State = "have" | "suggested" | "missing";

interface Cell {
  text: string; // Devanagari
  state: State;
  group: Group | null; // the labelled group, or the group suggested as this letter
  samples: number;
}

/** Every letter of the table (consonants, optionally the conjuncts, and the vowels) in rows. */
function rowsOf(conjuncts: boolean): { head: string; letters: string[] }[] {
  const bases = conjuncts ? [...CONSONANTS, ...CONJUNCTS] : CONSONANTS;
  return [{ head: "अ", letters: VOWELS }, ...bases.map((c) => ({ head: c, letters: SIGNS.map((sg) => c + sg) }))];
}

function cellsOf(groups: Group[], letters: string[]): Map<string, Cell> {
  const labelled = new Map<string, Group[]>();
  const suggested = new Map<string, Group[]>();
  for (const g of groups) {
    if (g.label_dev) labelled.set(g.label_dev, [...(labelled.get(g.label_dev) ?? []), g]);
    else if (g.suggestion) suggested.set(g.suggestion.label_dev, [...(suggested.get(g.suggestion.label_dev) ?? []), g]);
  }
  const out = new Map<string, Cell>();
  for (const text of letters) {
    const own = labelled.get(text);
    const sug = suggested.get(text);
    if (own) out.set(text, { text, state: "have", group: own[0], samples: own.reduce((n, g) => n + g.samples, 0) });
    else if (sug) {
      const best = [...sug].sort((a, b) => b.samples - a.samples)[0];
      out.set(text, { text, state: "suggested", group: best, samples: best.samples });
    } else out.set(text, { text, state: "missing", group: null, samples: 0 });
  }
  return out;
}

/** How many letters of the table (without conjuncts) have no labelled group: shown in the side bar. */
export function missingCount(groups: Group[]): number {
  const letters = rowsOf(false).flatMap((r) => r.letters);
  return [...cellsOf(groups, letters).values()].filter((c) => c.state !== "have").length;
}

/** Labelled groups whose label is not a letter of the table, in label order. */
export function otherLabelled(groups: Group[], conjuncts: boolean): Group[] {
  const inTable = new Set(rowsOf(conjuncts).flatMap((r) => r.letters));
  return groups
    .filter((g) => g.label_dev && !inTable.has(g.label_dev))
    .sort((a, b) => (a.label_dev < b.label_dev ? -1 : a.label_dev > b.label_dev ? 1 : a.code < b.code ? -1 : 1));
}

export default function LetterOverview({ ctx }: { ctx: ReviewContext }) {
  const [conjuncts, setConjuncts] = useState(false);
  const [hideEmpty, setHideEmpty] = useState(false);
  const rows = useMemo(() => rowsOf(conjuncts), [conjuncts]);
  const cells = useMemo(() => cellsOf(ctx.groups, rows.flatMap((r) => r.letters)), [ctx.groups, rows]);
  const others = useMemo(() => otherLabelled(ctx.groups, conjuncts), [ctx.groups, conjuncts]);
  const all = [...cells.values()];
  const have = all.filter((c) => c.state === "have").length;
  const suggested = all.filter((c) => c.state === "suggested").length;
  const missing = all.length - have - suggested;
  // rows with nothing labelled or suggested yet (rare consonants) can be hidden to focus on the others
  const shown = hideEmpty ? rows.filter((r) => r.letters.some((t) => cells.get(t)!.state !== "missing")) : rows;
  const hidden = rows.length - shown.length;

  return (
    <div className="missing-letters">
      <h2>Letter overview</h2>
      <p className="small muted">
        Every consonant with every vowel sign, and the vowels: {all.length} letters. <strong>{have}</strong> have a
        labelled group, <strong>{suggested}</strong> are only suggested for a group (amber: click to review it),{" "}
        <strong>{missing}</strong> have none yet. Many combinations are rare in any text, so not all of them will
        appear in a book.
      </p>
      <div className="row small">
        <label className="row">
          <input type="checkbox" checked={conjuncts} onChange={(e) => setConjuncts(e.target.checked)} />
          Include the conjuncts {CONJUNCTS.map(toGujarati).join(" ")}
        </label>
        <label className="row" title="Hide the rows where no letter has a group or a suggestion yet">
          <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} />
          Hide rows with no group yet{hideEmpty && hidden > 0 ? ` (${hidden} hidden)` : ""}
        </label>
        <span className="legend">
          <span className="cell-have">labelled</span> <span className="cell-suggested">suggested</span>{" "}
          <span className="cell-missing">missing</span>
        </span>
      </div>
      <div className="missing-table-wrap">
        <table className="missing-table" aria-label="Letters and their groups">
          <thead>
            <tr>
              <th />
              {SIGNS.map((sg) => (
                <th key={sg || "none"} scope="col">
                  {sg ? toGujarati("◌" + sg) : "—"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.head}>
                <th scope="row">{r.head === "अ" ? "vowels" : toGujarati(r.head)}</th>
                {r.letters.map((t) => {
                  const c = cells.get(t)!;
                  const label = toGujarati(t);
                  const title =
                    c.state === "have"
                      ? `${label} (${t}): ${c.samples} letters in ${c.group!.code}`
                      : c.state === "suggested"
                        ? `${label} (${t}): no labelled group; ${c.group!.code} (${c.samples} letters) is suggested as it`
                        : `${label} (${t}): no group yet`;
                  return (
                    <td key={t} className={`cell-${c.state}`}>
                      {c.group ? (
                        <button
                          className="link"
                          title={title}
                          onClick={() => go(`/books/${ctx.bookId}/review/${c.group!.id}`)}
                        >
                          {label}
                          {c.state === "have" && <span className="cell-count">{c.samples}</span>}
                        </button>
                      ) : (
                        <span title={title}>{label}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Other labelled groups</h3>
      {others.length === 0 ? (
        <p className="small muted">Every labelled group is a letter of the table above.</p>
      ) : (
        <>
          <p className="small muted">
            Labels that are not in the table: words, conjuncts{conjuncts ? " other than the four above" : ""}, letters
            with ં or ઃ, dandas and digits ({others.length}).
          </p>
          <div className="other-labels" aria-label="Other labelled groups">
            {others.map((g) => (
              <button
                key={g.id}
                className="other-label"
                title={`${g.label_guj} (${g.label_dev}): ${g.samples} letters in ${g.code}`}
                onClick={() => go(`/books/${ctx.bookId}/review/${g.id}`)}
              >
                {g.label_guj}
                <span className="cell-count">{g.samples}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
