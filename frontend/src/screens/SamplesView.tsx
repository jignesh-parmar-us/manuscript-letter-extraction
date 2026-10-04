// The unsure samples (not in any group), or the deleted ones.
// Unsure: each sample shows its suggested group; click the suggestion (or select samples and press
// A) to accept it; select samples to make a new group (N) or move them to a group.
// Deleted: select samples and restore them (they come back as unsure).
import { MouseEvent, useCallback, useEffect, useState } from "react";
import { api, Sample } from "../api";
import ErrorBox from "../components/ErrorBox";
import SampleGrid from "../components/SampleGrid";
import { emptySelection, select } from "../components/selection";
import { usePagedSamples } from "../components/usePagedSamples";
import { go } from "../route";
import { isTyping, ReviewContext } from "./Review";

export default function SamplesView({ kind, ctx }: { kind: "unsure" | "deleted"; ctx: ReviewContext }) {
  const { bookId, selection, setSelection, act } = ctx;
  const load = useCallback(
    (offset: number, limit: number) =>
      kind === "unsure" ? api.unsure(bookId, offset, limit) : api.deleted(bookId, offset, limit),
    [kind, bookId],
  );
  const { samples, total, more, error } = usePagedSamples(load, ctx.version);
  const [moveTo, setMoveTo] = useState("");
  const ids = [...selection.ids];
  const order = samples.map((s) => s.id);
  const targets = ctx.groups.filter((g) => g.samples > 0 || g.label_dev);

  const onClick = (id: number, e: MouseEvent) =>
    setSelection(select(selection, order, id, { shift: e.shiftKey, toggle: e.metaKey || e.ctrlKey }));

  /** Accept the suggested group of these samples: one move per suggested group. */
  const accept = useCallback(
    async (chosen: Sample[]) => {
      const byGroup = new Map<number, number[]>();
      chosen.forEach((s) => s.suggestion && byGroup.set(s.suggestion.group_id, [...(byGroup.get(s.suggestion.group_id) ?? []), s.id]));
      for (const [gid, sids] of byGroup) await act(() => api.move(bookId, sids, gid));
      setSelection(emptySelection());
    },
    [act, bookId, setSelection],
  );
  const toNewGroup = useCallback(async () => {
    if (!ids.length) return;
    const r = await act(() => api.newGroup(bookId, ids));
    setSelection(emptySelection());
    if (r?.group_id) go(`/books/${bookId}/review/${r.group_id}`);
  }, [ids, act, bookId, setSelection]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e)) return;
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "a") {
        e.preventDefault();
        setSelection({ ids: new Set(order), anchor: null });
      } else if (k === "escape") setSelection(emptySelection());
      else if (kind === "unsure" && !e.metaKey && !e.ctrlKey && k === "a")
        accept(samples.filter((s) => selection.ids.has(s.id)));
      else if (kind === "unsure" && !e.metaKey && !e.ctrlKey && k === "n") toNewGroup();
      else if (kind === "unsure" && (k === "delete" || k === "backspace") && ids.length)
        act(() => api.deleteSamples(bookId, ids)).then(() => setSelection(emptySelection()));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, samples, selection, ids, kind, accept, toNewGroup, act, bookId, setSelection]);

  const withSuggestion = samples.filter((s) => selection.ids.has(s.id) && s.suggestion);

  return (
    <div>
      <ErrorBox error={error} />
      <h2>
        {kind === "unsure" ? "Unsure" : "Deleted samples"} <span className="muted">({total})</span>
      </h2>
      <p className="muted small">
        {kind === "unsure"
          ? "Samples in no group. Accept a suggestion (→), or select samples and make a new group or move them."
          : "Deleted samples are left out of groups and the export. Restoring puts them back as unsure."}
      </p>
      <div className="toolbar row">
        <span className="small muted">{ids.length > 0 ? `${ids.length} selected` : "Click samples to select them"}</span>
        {kind === "unsure" ? (
          <>
            <button disabled={!withSuggestion.length} onClick={() => accept(withSuggestion)} title="A">
              Accept suggestions ({withSuggestion.length})
            </button>
            <button disabled={!ids.length} onClick={toNewGroup} title="N">
              New group
            </button>
            <select aria-label="Move selected to group" value={moveTo} disabled={!ids.length} onChange={(e) => setMoveTo(e.target.value)}>
              <option value="">Move to group…</option>
              {targets.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label_guj ? `${g.label_guj} (${g.code})` : g.code} · {g.samples}
                </option>
              ))}
            </select>
            <button
              disabled={!ids.length || !moveTo}
              onClick={() =>
                act(() => api.move(bookId, ids, Number(moveTo))).then(() => {
                  setSelection(emptySelection());
                  setMoveTo("");
                })
              }
            >
              Move
            </button>
            <button
              className="danger"
              disabled={!ids.length}
              onClick={() => act(() => api.deleteSamples(bookId, ids)).then(() => setSelection(emptySelection()))}
            >
              Delete
            </button>
          </>
        ) : (
          <button
            disabled={!ids.length}
            onClick={() => act(() => api.restoreSamples(bookId, ids)).then(() => setSelection(emptySelection()))}
          >
            Restore
          </button>
        )}
      </div>
      <SampleGrid samples={samples} selected={selection.ids} onClick={onClick} onAccept={(s) => accept([s])} />
      {samples.length < total && (
        <button onClick={more}>
          Show more ({samples.length} of {total})
        </button>
      )}
    </div>
  );
}
