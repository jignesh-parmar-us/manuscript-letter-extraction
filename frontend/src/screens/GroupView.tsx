// One group: its label, status and samples (nearest to the group's centre first).
// Select samples and move them out (to Unsure, another group, a new group) or delete them;
// label the group; mark it reviewed or lock it; merge another group into it (chosen in the letter
// table, GroupPicker.tsx); dissolve it.
// Keys: U = selected to Unsure, N = new group from selection, Delete = delete selection,
//       Ctrl/Cmd+A = select all, Esc = clear selection.
// With OCR readings (C11, C12): the suggested label to accept, change or reject; what the samples
// were read as; and a badge on each sample whose reading differs from the group's.
// One selected letter shows its line (LineContext); double-click opens it on its page, and the
// Pages tab's "Back" returns here, to that letter (returnSpot.ts).
import { MouseEvent, useCallback, useEffect, useState } from "react";
import { api, Group, Sample } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import LabelPicker from "../components/LabelPicker";
import LineContext from "../components/LineContext";
import { openOnPage, useArrive, useComeBack } from "../components/returnSpot";
import SampleGrid from "../components/SampleGrid";
import { emptySelection, select } from "../components/selection";
import { usePagedSamples } from "../components/usePagedSamples";
import { go } from "../route";
import { isTyping, ReviewContext } from "./Review";
import GroupPicker, { MoveTarget } from "./GroupPicker";
import { expectedReading, ReadingsLine, SuggestionChip } from "./Suggestions";

export default function GroupView({ group, ctx }: { group: Group; ctx: ReviewContext }) {
  const { bookId, selection, setSelection, act } = ctx;
  const load = useCallback((offset: number, limit: number) => api.groupSamples(group.id, offset, limit), [group.id]);
  const back = useComeBack();
  const { samples, total, more, error, loading } = usePagedSamples(load, ctx.version, back.first);
  useArrive(back, samples, loading, (id) => setSelection({ ids: new Set([id]), anchor: id }));
  const [picking, setPicking] = useState(false); // the "Move to…" picker is open
  const [merging, setMerging] = useState(false); // the picker for "Merge another group into this one…"
  const [changeTo, setChangeTo] = useState<string | null>(null); // "Change…" on the suggestion fills the picker
  const [dialog, confirm] = useConfirm();
  const ids = [...selection.ids];
  const order = samples.map((s) => s.id);
  const withReading = samples.filter((s) => selection.ids.has(s.id) && s.reading).map((s) => s.id);

  const single = ids.length === 1 ? samples.find((s) => s.id === ids[0]) ?? null : null;
  const open = (s: Sample) =>
    openOnPage(bookId, s, samples, group.label_guj ? `${group.label_guj} (${group.code})` : group.code);

  const onClick = (id: number, e: MouseEvent) => {
    back.clear();
    setSelection(select(selection, order, id, { shift: e.shiftKey, toggle: e.metaKey || e.ctrlKey }));
  };

  const toUnsure = useCallback(() => {
    if (ids.length) act(() => api.move(bookId, ids, null)).then(() => setSelection(emptySelection()));
  }, [ids, act, bookId, setSelection]);
  const toNewGroup = useCallback(async () => {
    if (!ids.length) return;
    const r = await act(() => api.newGroup(bookId, ids));
    setSelection(emptySelection());
    if (r?.group_id) go(`/books/${bookId}/review/${r.group_id}`);
  }, [ids, act, bookId, setSelection]);
  const remove = useCallback(() => {
    if (ids.length) act(() => api.deleteSamples(bookId, ids)).then(() => setSelection(emptySelection()));
  }, [ids, act, bookId, setSelection]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || group.locked) return;
      const k = e.key.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === "a") {
        e.preventDefault();
        setSelection({ ids: new Set(order), anchor: null });
      } else if (k === "escape") setSelection(emptySelection());
      else if (!e.metaKey && !e.ctrlKey && k === "u") toUnsure();
      else if (!e.metaKey && !e.ctrlKey && k === "n") toNewGroup();
      else if (k === "delete" || k === "backspace") remove();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, toUnsure, toNewGroup, remove, setSelection, group.locked]);

  async function moveTo(target: MoveTarget) {
    setPicking(false);
    await act(() =>
      "label" in target ? api.labelSamples(bookId, ids, target.label) : api.move(bookId, ids, target.groupId),
    );
    setSelection(emptySelection());
  }

  async function dissolve() {
    if (await confirm(`Send all ${group.samples} samples of ${group.code} to Unsure and remove the group?`, "Dissolve"))
      act(() => api.dissolve(bookId, group.id)).then((r) => r && go(`/books/${bookId}/review/unsure`));
  }

  const locked = group.locked;
  return (
    <div>
      {dialog}
      {picking && (
        <GroupPicker groups={ctx.groups} count={ids.length} currentGroupId={group.id} onPick={moveTo} onClose={() => setPicking(false)} />
      )}
      {merging && (
        <GroupPicker
          mode="merge"
          into={group.label_guj ? `${group.label_guj} (${group.code})` : group.code}
          groups={ctx.groups}
          count={0}
          currentGroupId={group.id}
          onPick={(t) => {
            setMerging(false);
            if ("groupId" in t) act(() => api.merge(bookId, group.id, [t.groupId]));
          }}
          onClose={() => setMerging(false)}
        />
      )}
      <ErrorBox error={error} />
      <div className="group-head">
        <div>
          <span className="big-letter">{group.label_guj || "—"}</span>{" "}
          {group.label_dev && <span className="big-letter muted">{group.label_dev}</span>}
          <div className="muted small">
            {group.code} · {group.kind} · {group.samples} samples ({group.red} red, {group.black} black)
            {group.spread !== null && ` · spread ${group.spread}`}
          </div>
        </div>
        <div className="row">
          <label className="row small">
            <input
              type="checkbox"
              checked={group.status !== "auto"}
              disabled={locked}
              onChange={(e) => act(() => api.status(bookId, group.id, { reviewed: e.target.checked }))}
            />
            Reviewed
          </label>
          <label className="row small">
            <input
              type="checkbox"
              checked={locked}
              onChange={(e) => act(() => api.status(bookId, group.id, { locked: e.target.checked }))}
            />
            Locked
          </label>
        </div>
      </div>

      <SuggestionChip group={group} ctx={ctx} onChange={setChangeTo} />
      <ReadingsLine group={group} ctx={ctx} />

      {/* the label and the actions stay at the top of the window while the letters scroll (sticky) */}
      <div className="sticky-tools sticky-block">
        <div className="row sticky-label">
          <span className="sticky-title" title={`${group.code}${group.label_dev ? ` · ${group.label_dev}` : ""}`}>
            {group.label_guj || group.code}
          </span>
          <LabelPicker
            key={changeTo ?? ""}
            initialText={changeTo ?? undefined}
            bookId={bookId}
            current={{ dev: group.label_dev, guj: group.label_guj }}
            disabled={locked}
            groupId={group.id}
            onSave={async (text) => !!(await act(() => api.label(bookId, group.id, text)))}
            onMerge={async (target) => {
              if (await confirm(`Merge ${group.code} (${group.samples} samples) into ${target.code}?`, "Merge")) {
                const r = await act(() => api.merge(bookId, target.id, [group.id]));
                if (r) go(`/books/${bookId}/review/${target.id}`);
                return !!r;
              }
              return false;
            }}
          />
        </div>
        {locked && <p className="muted small">The group is locked: unlock it to change it.</p>}
        <div className="toolbar row" aria-label="Actions on the selected letters">
          <span className="small muted">
            {ids.length > 0 ? `${ids.length} selected` : "Click samples to select them"}
          </span>
          <button disabled={locked || !ids.length} onClick={toUnsure} title="U">
            To Unsure
          </button>
          <button disabled={locked || !ids.length} onClick={toNewGroup} title="N">
            New group
          </button>
          <button disabled={locked || !ids.length} onClick={() => setPicking(true)} title="Move to a letter's group or another group">
            Move to…
          </button>
          <button className="danger" disabled={locked || !ids.length} onClick={remove} title="Delete">
            Delete
          </button>
          <button
            disabled={!withReading.length}
            onClick={() => act(() => api.removeReadings(bookId, withReading)).then(() => setSelection(emptySelection()))}
            title="The selected letters' readings are wrong: remove them (the letters stay in the group)"
          >
            Remove readings{withReading.length ? ` (${withReading.length})` : ""}
          </button>
        </div>
        <LineContext sample={single} version={ctx.version} onOpen={open} />
      </div>
      {back.note && <p className="small muted">{back.note}</p>}

      <SampleGrid samples={samples} selected={selection.ids} onClick={onClick} expected={expectedReading(group)}
        onRemoveReading={(s) => act(() => api.removeReadings(bookId, [s.id]))}
        onOpen={open} marked={back.marked}
      />
      {samples.length < total && (
        <button onClick={more}>
          Show more ({samples.length} of {total})
        </button>
      )}

      <div className="row toolbar">
        <button disabled={locked} onClick={() => setMerging(true)} title="Choose a group from the letter table">
          Merge another group into this one…
        </button>
        <button className="danger" disabled={locked} onClick={dissolve}>
          Dissolve group
        </button>
      </div>
    </div>
  );
}
