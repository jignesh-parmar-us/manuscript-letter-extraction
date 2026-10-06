// "Letter overview" in the Review tab: every consonant with every vowel sign (and the vowels), and
// which of them have no labelled group yet. A letter with a labelled group links to it; a letter
// that no group has as its label but some group is suggested as, links to that group to review.
// Optional rows: the conjuncts क्ष त्र ज्ञ श्र, every consonant with rakar (क्र; ट्र and ड्र are drawn
// with the bottom churn) and every consonant with reph (र्क).
// Labels are matched exactly (Devanagari, as stored); a word label does not count for its letters.
// Below the table, every labelled group whose label is not in it (words, other joined letters,
// letters with a mark, dandas, digits), so the page shows every label of the book.
// The table itself (`LetterTable`, `RowChoice`) is also the "Move to" picker's (GroupPicker.tsx).
import { ReactNode, useMemo, useState } from "react";
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
export const RAKAR = "्र";
export const REPH = "र्";

/** Optional rows of the table. */
export type Extra = "conjuncts" | "rakar" | "reph";
export const EXTRAS: { key: Extra; label: string; title: string }[] = [
  { key: "conjuncts", label: `Conjuncts ${CONJUNCTS.map(toGujarati).join(" ")}`, title: "The four common conjuncts" },
  {
    key: "rakar",
    label: "With rakar ્ર (ક્ર, ટ્ર)",
    title: "Every consonant with rakar below it (ક્ર, પ્ર); on ટ and ડ it is drawn as the bottom churn (ટ્ર, ડ્ર)",
  },
  { key: "reph", label: "With reph ર્ (ર્ક)", title: "Every consonant with reph above it (ર્ક, ર્મ)" },
];

type State = "have" | "suggested" | "missing";

export interface Cell {
  text: string; // Devanagari
  state: State;
  group: Group | null; // the labelled group, or the group suggested as this letter
  samples: number;
}

export interface Row {
  head: string; // the row's base: a consonant, a conjunct, क्र, र्क ... ("अ" for the vowels)
  section: string; // rows are shown in sections: "", "Conjuncts", "With rakar", "With reph"
  letters: string[];
}

/** The rows of the table: the vowels and every consonant, and the chosen extra rows. */
export function rowsOf(extras: Iterable<Extra> = []): Row[] {
  const on = new Set(extras);
  const withSigns = (head: string, section: string): Row => ({ head, section, letters: SIGNS.map((sg) => head + sg) });
  const rows: Row[] = [{ head: "अ", section: "", letters: VOWELS }, ...CONSONANTS.map((c) => withSigns(c, ""))];
  if (on.has("conjuncts")) rows.push(...CONJUNCTS.map((c) => withSigns(c, "Conjuncts")));
  // र with rakar or reph (र्र) is not written that way
  if (on.has("rakar")) rows.push(...CONSONANTS.filter((c) => c !== "र").map((c) => withSigns(c + RAKAR, "With rakar ્ર")));
  if (on.has("reph")) rows.push(...CONSONANTS.filter((c) => c !== "र").map((c) => withSigns(REPH + c, "With reph ર્")));
  return rows;
}

export function cellsOf(groups: Group[], letters: string[]): Map<string, Cell> {
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

/** How many letters of the basic table (vowels and consonants) have no labelled group: for the side bar. */
export function missingCount(groups: Group[]): number {
  const letters = rowsOf().flatMap((r) => r.letters);
  return [...cellsOf(groups, letters).values()].filter((c) => c.state !== "have").length;
}

/** Labelled groups whose label is not a letter of the table, in label order. */
export function otherLabelled(groups: Group[], extras: Iterable<Extra> = []): Group[] {
  const inTable = new Set(rowsOf(extras).flatMap((r) => r.letters));
  return groups
    .filter((g) => g.label_dev && !inTable.has(g.label_dev))
    .sort((a, b) => (a.label_dev < b.label_dev ? -1 : a.label_dev > b.label_dev ? 1 : a.code < b.code ? -1 : 1));
}

/** Check boxes for the optional rows (and, where wanted, for hiding the rows with nothing yet). */
export function RowChoice(props: {
  extras: Set<Extra>;
  onChange: (extras: Set<Extra>) => void;
  hideEmpty?: boolean;
  onHideEmpty?: (hide: boolean) => void;
  hidden?: number;
}) {
  function toggle(key: Extra) {
    const next = new Set(props.extras);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    props.onChange(next);
  }
  return (
    <div className="row small row-choice">
      {EXTRAS.map((e) => (
        <label key={e.key} className="row" title={e.title}>
          <input type="checkbox" checked={props.extras.has(e.key)} onChange={() => toggle(e.key)} />
          {e.label}
        </label>
      ))}
      {props.onHideEmpty && (
        <label className="row" title="Hide the rows where no letter has a group or a suggestion yet">
          <input type="checkbox" checked={!!props.hideEmpty} onChange={(e) => props.onHideEmpty!(e.target.checked)} />
          Hide rows with no group yet{props.hideEmpty && props.hidden ? ` (${props.hidden} hidden)` : ""}
        </label>
      )}
    </div>
  );
}

/** The table of letters. A cell is a button when `canPick(cell)`; `title(cell)` explains it. */
export function LetterTable(props: {
  rows: Row[];
  cells: Map<string, Cell>;
  onPick: (cell: Cell) => void;
  canPick: (cell: Cell) => boolean;
  title: (cell: Cell, label: string) => string;
  label?: string;
}) {
  const body: ReactNode[] = [];
  let section = "";
  for (const r of props.rows) {
    if (r.section !== section) {
      section = r.section;
      body.push(
        <tr key={`section-${section}`} className="table-section">
          <th colSpan={SIGNS.length + 1}>{section}</th>
        </tr>,
      );
    }
    body.push(
      <tr key={r.head}>
        <th scope="row">{r.head === "अ" ? "vowels" : toGujarati(r.head)}</th>
        {r.letters.map((t) => {
          const c = props.cells.get(t)!;
          const label = toGujarati(t);
          const title = props.title(c, label);
          return (
            <td key={t} className={`cell-${c.state}`}>
              {props.canPick(c) ? (
                <button className="link" title={title} onClick={() => props.onPick(c)}>
                  {label}
                  {c.state === "have" && <span className="cell-count">{c.samples}</span>}
                </button>
              ) : (
                <span title={title}>{label}</span>
              )}
            </td>
          );
        })}
      </tr>,
    );
  }
  return (
    <div className="missing-table-wrap">
      <table className="missing-table" aria-label={props.label ?? "Letters and their groups"}>
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
        <tbody>{body}</tbody>
      </table>
    </div>
  );
}

export function Legend() {
  return (
    <span className="legend small">
      <span className="cell-have">labelled</span> <span className="cell-suggested">suggested</span>{" "}
      <span className="cell-missing">missing</span>
    </span>
  );
}

export default function LetterOverview({ ctx }: { ctx: ReviewContext }) {
  const [extras, setExtras] = useState<Set<Extra>>(new Set());
  const [hideEmpty, setHideEmpty] = useState(false);
  const rows = useMemo(() => rowsOf(extras), [extras]);
  const cells = useMemo(() => cellsOf(ctx.groups, rows.flatMap((r) => r.letters)), [ctx.groups, rows]);
  const others = useMemo(() => otherLabelled(ctx.groups, extras), [ctx.groups, extras]);
  const all = [...cells.values()];
  const have = all.filter((c) => c.state === "have").length;
  const suggested = all.filter((c) => c.state === "suggested").length;
  const missing = all.length - have - suggested;
  // rows with nothing labelled or suggested yet (rare consonants) can be hidden to focus on the others
  const shown = hideEmpty ? rows.filter((r) => r.letters.some((t) => cells.get(t)!.state !== "missing")) : rows;

  return (
    <div className="missing-letters">
      <h2>Letter overview</h2>
      <p className="small muted">
        Every consonant with every vowel sign, and the vowels{extras.size ? ", with the rows chosen below" : ""}:{" "}
        {all.length} letters. <strong>{have}</strong> have a labelled group, <strong>{suggested}</strong> are only
        suggested for a group (amber: click to review it), <strong>{missing}</strong> have none yet. Many combinations
        are rare in any text, so not all of them will appear in a book.
      </p>
      <div className="row">
        <RowChoice
          extras={extras}
          onChange={setExtras}
          hideEmpty={hideEmpty}
          onHideEmpty={setHideEmpty}
          hidden={rows.length - shown.length}
        />
        <Legend />
      </div>
      <LetterTable
        rows={shown}
        cells={cells}
        canPick={(c) => !!c.group}
        onPick={(c) => go(`/books/${ctx.bookId}/review/${c.group!.id}`)}
        title={(c, label) =>
          c.state === "have"
            ? `${label} (${c.text}): ${c.samples} letters in ${c.group!.code}`
            : c.state === "suggested"
              ? `${label} (${c.text}): no labelled group; ${c.group!.code} (${c.samples} letters) is suggested as it`
              : `${label} (${c.text}): no group yet`
        }
      />

      <h3>Other labelled groups</h3>
      {others.length === 0 ? (
        <p className="small muted">Every labelled group is a letter of the table above.</p>
      ) : (
        <>
          <p className="small muted">
            Labels that are not in the table: words, other joined letters, letters with ં or ઃ, dandas and digits (
            {others.length}).
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
