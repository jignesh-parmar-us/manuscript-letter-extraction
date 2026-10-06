// A group chosen from the letter table instead of a long list, in two modes:
// - "move" ("Move to…"): where to put the selected letters. A letter of the table: into the group with
//   that label, or into a new group that gets the label;
// - "merge" ("Merge another group into this one…"): which group to merge into the current one. Only
//   letters with a group (labelled, or an unlabelled group suggested as the letter) can be chosen.
// Below the table in both: the other labelled groups (words, other joined letters, dandas, digits)
// and the groups without a label, newest first, 30 at a time ("Show more").
// The current group and locked groups cannot be chosen. Drawn into <body> like the confirm dialog.
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Group } from "../api";
import { toGujarati } from "../components/LabelPicker";
import { Cell, cellsOf, Extra, LetterTable, Legend, otherLabelled, RowChoice, rowsOf } from "./LetterOverview";

export type MoveTarget = { groupId: number; name: string } | { label: string };

const PAGE = 30;

interface Props {
  groups: Group[];
  count: number; // letters to move ("move" mode)
  currentGroupId?: number | null;
  mode?: "move" | "merge";
  into?: string; // "merge" mode: the current group's name, for the title
  onPick: (target: MoveTarget) => void;
  onClose: () => void;
}

export default function GroupPicker({ groups, count, currentGroupId = null, mode = "move", into = "", onPick, onClose }: Props) {
  const merging = mode === "merge";
  const [extras, setExtras] = useState<Set<Extra>>(new Set());
  const [shown, setShown] = useState(PAGE);
  const rows = useMemo(() => rowsOf(extras), [extras]);
  const cells = useMemo(() => cellsOf(groups, rows.flatMap((r) => r.letters)), [groups, rows]);
  const others = useMemo(() => otherLabelled(groups, extras), [groups, extras]);
  const unlabelled = useMemo(
    () =>
      groups
        .filter((g) => !g.label_dev && g.samples > 0 && g.id !== currentGroupId)
        .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "") || b.id - a.id),
    [groups, currentGroupId],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const usable = (g: Group | null) => !!g && !g.locked && g.id !== currentGroupId;
  const pickCell = (c: Cell) =>
    c.group && (c.state === "have" || merging)
      ? onPick({ groupId: c.group.id, name: `${toGujarati(c.text)} (${c.group.code})` })
      : onPick({ label: c.text });
  const what = count === 1 ? "the letter" : `the ${count} letters`;
  const verb = merging ? "Merge" : "Move into";

  return createPortal(
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog picker" role="dialog" aria-modal="true" aria-label={merging ? "Merge a group" : "Move to"}>
        <div className="row between">
          <h2>{merging ? `Merge a group into ${into}` : `Move ${what} to…`}</h2>
          <button onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="small muted">
          {merging
            ? "Click a letter with a group (green, or amber for an unlabelled group suggested as it), or a group below: all its letters join this group."
            : `Click a letter: ${what} go into its group, or into a new group with that label if there is none yet. Or choose another group below.`}
        </p>
        <div className="row">
          <RowChoice extras={extras} onChange={setExtras} />
          <Legend />
        </div>
        <LetterTable
          label={merging ? "Letters whose group to merge" : "Letters to move to"}
          rows={rows}
          cells={cells}
          canPick={(c) => (c.state === "have" || (merging && c.group) ? usable(c.group) : !merging)}
          onPick={pickCell}
          title={(c, label) =>
            c.group && (c.state === "have" || merging)
              ? c.group.id === currentGroupId
                ? `${label}: this group`
                : c.group.locked
                  ? `${label}: ${c.group.code} is locked`
                  : `${verb} ${label} (${c.group.code}, ${c.samples} letters)`
              : merging
                ? `${label} (${c.text}): no group to merge`
                : `Put them in a new group labelled ${label} (${c.text})`
          }
        />

        {others.length > 0 && (
          <>
            <h3>Other labelled groups</h3>
            <div className="other-labels" aria-label="Other labelled groups">
              {others.map((g) => (
                <button
                  key={g.id}
                  className="other-label"
                  disabled={!usable(g)}
                  title={`${verb} ${g.label_guj} (${g.code}, ${g.samples} letters)`}
                  onClick={() => onPick({ groupId: g.id, name: `${g.label_guj} (${g.code})` })}
                >
                  {g.label_guj}
                  <span className="cell-count">{g.samples}</span>
                </button>
              ))}
            </div>
          </>
        )}

        <h3>Groups without a label</h3>
        {unlabelled.length === 0 ? (
          <p className="small muted">None.</p>
        ) : (
          <>
            <p className="small muted">Newest first ({unlabelled.length}).</p>
            <div className="picker-groups" aria-label="Groups without a label">
              {unlabelled.slice(0, shown).map((g) => (
                <button
                  key={g.id}
                  className="picker-group"
                  disabled={g.locked}
                  title={`${verb} ${g.code} (${g.samples} letters)${g.suggestion ? `, suggested ${g.suggestion.label_guj}` : ""}`}
                  onClick={() => onPick({ groupId: g.id, name: g.code })}
                >
                  {g.example_image ? <img src={g.example_image} alt="" /> : <span className="thumb" />}
                  <span className="small">{g.code}</span>
                  <span className="muted small">{g.samples}</span>
                </button>
              ))}
            </div>
            {shown < unlabelled.length && (
              <button onClick={() => setShown((n) => n + PAGE)}>Show more ({unlabelled.length - shown} left)</button>
            )}
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
