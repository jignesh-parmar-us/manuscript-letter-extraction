// The unsure samples (not in any group), or the deleted ones.
// Unsure: each sample shows its suggested group; click the suggestion (or select samples and press
// A) to accept it; select samples to make a new group (N) or move them to a group.
// Deleted: select samples and restore them (they come back as unsure).
// On printed books read with Tesseract (C12), unsure samples with a confident reading show it as a
// second chip: accepting it puts the sample in the group with that label, or a new group that gets it.
// One selected letter shows its line; double-click opens it on its page, and "Back" there returns here.
import { MouseEvent, useCallback, useEffect, useState } from "react";
import { api, Sample } from "../api";
import ErrorBox from "../components/ErrorBox";
import LineContext from "../components/LineContext";
import { openOnPage, useArrive, useComeBack } from "../components/returnSpot";
import SampleGrid from "../components/SampleGrid";
import { emptySelection, select } from "../components/selection";
import { usePagedSamples } from "../components/usePagedSamples";
import { go } from "../route";
import GroupPicker, { MoveTarget } from "./GroupPicker";
import { isTyping, ReviewContext } from "./Review";

export default function SamplesView({ kind, ctx }: { kind: "unsure" | "deleted"; ctx: ReviewContext }) {
  const { bookId, selection, setSelection, act } = ctx;
  const load = useCallback(
    (offset: number, limit: number) =>
      kind === "unsure" ? api.unsure(bookId, offset, limit) : api.deleted(bookId, offset, limit),
    [kind, bookId],
  );
  const back = useComeBack();
  const { samples, total, more, error, loading } = usePagedSamples(load, ctx.version, back.first);
  useArrive(back, samples, loading, (id) => setSelection({ ids: new Set([id]), anchor: id }));
  const [picking, setPicking] = useState(false); // the "Move to…" picker is open
  const ids = [...selection.ids];
  const order = samples.map((s) => s.id);

  const single = ids.length === 1 ? samples.find((s) => s.id === ids[0]) ?? null : null;
  const open = (s: Sample) => openOnPage(bookId, s, samples, kind === "unsure" ? "Unsure" : "Deleted samples");

  const onClick = (id: number, e: MouseEvent) => {
    back.clear();
    setSelection(select(selection, order, id, { shift: e.shiftKey, toggle: e.metaKey || e.ctrlKey }));
  };

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
  /** Put samples under their OCR readings' labels: one action per label. */
  const acceptReadings = useCallback(
    async (chosen: Sample[]) => {
      const byLabel = new Map<string, number[]>();
      chosen.forEach((s) => s.reading && byLabel.set(s.reading.label_dev, [...(byLabel.get(s.reading.label_dev) ?? []), s.id]));
      for (const [label, sids] of byLabel) await act(() => api.labelSamples(bookId, sids, label));
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

  async function moveTo(target: MoveTarget) {
    setPicking(false);
    await act(() =>
      "label" in target ? api.labelSamples(bookId, ids, target.label) : api.move(bookId, ids, target.groupId),
    );
    setSelection(emptySelection());
  }

  const withSuggestion = samples.filter((s) => selection.ids.has(s.id) && s.suggestion);
  const withReading = samples.filter((s) => selection.ids.has(s.id) && s.reading);

  return (
    <div>
      <ErrorBox error={error} />
      <h2>
        {kind === "unsure" ? "Unsure" : "Deleted samples"} <span className="muted">({total})</span>
      </h2>
      <p className="muted small">
        {kind === "unsure"
          ? "Samples in no group. Accept a suggested group (→) or a Tesseract reading (green, top right), or select samples and make a new group or move them."
          : "Deleted samples are left out of groups and the export. Restoring puts them back as unsure."}
      </p>
      {picking && <GroupPicker groups={ctx.groups} count={ids.length} onPick={moveTo} onClose={() => setPicking(false)} />}
      <div className="toolbar row sticky-tools" aria-label="Actions on the selected letters">
        <span className="sticky-title">{kind === "unsure" ? "Unsure" : "Deleted"}</span>
        <span className="small muted">{ids.length > 0 ? `${ids.length} selected` : "Click samples to select them"}</span>
        {kind === "unsure" ? (
          <>
            <button disabled={!withSuggestion.length} onClick={() => accept(withSuggestion)} title="A">
              Accept suggestions ({withSuggestion.length})
            </button>
            {samples.some((s) => s.reading) && (
              <button disabled={!withReading.length} onClick={() => acceptReadings(withReading)}>
                Accept readings ({withReading.length})
              </button>
            )}
            <button disabled={!ids.length} onClick={toNewGroup} title="N">
              New group
            </button>
            <button disabled={!ids.length} onClick={() => setPicking(true)} title="Move to a letter's group or another group">
              Move to…
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
        <LineContext sample={single} version={ctx.version} onOpen={open} />
      </div>
      {back.note && <p className="small muted">{back.note}</p>}
      <SampleGrid samples={samples} selected={selection.ids} onClick={onClick} onAccept={(s) => accept([s])}
        onAcceptReading={kind === "unsure" ? (s) => acceptReadings([s]) : undefined}
        onOpen={open} marked={back.marked}
      />
      {samples.length < total && (
        <button onClick={more}>
          Show more ({samples.length} of {total})
        </button>
      )}
    </div>
  );
}
