// One group: its label, status and samples (nearest to the group's centre first).
// Select samples and move them out (to Unsure, another group, a new group) or delete them;
// label the group; mark it reviewed or lock it; merge another group into it; dissolve it.
// Keys: U = selected to Unsure, N = new group from selection, Delete = delete selection,
//       Ctrl/Cmd+A = select all, Esc = clear selection.
import { MouseEvent, useCallback, useEffect, useState } from "react";
import { api, Group } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import LabelPicker from "../components/LabelPicker";
import SampleGrid from "../components/SampleGrid";
import { emptySelection, select } from "../components/selection";
import { usePagedSamples } from "../components/usePagedSamples";
import { go } from "../route";
import { isTyping, ReviewContext } from "./Review";

export default function GroupView({ group, ctx }: { group: Group; ctx: ReviewContext }) {
  const { bookId, selection, setSelection, act } = ctx;
  const load = useCallback((offset: number, limit: number) => api.groupSamples(group.id, offset, limit), [group.id]);
  const { samples, total, more, error } = usePagedSamples(load, ctx.version);
  const [mergeWith, setMergeWith] = useState("");
  const [moveTo, setMoveTo] = useState("");
  const [dialog, confirm] = useConfirm();
  const ids = [...selection.ids];
  const order = samples.map((s) => s.id);
  const others = ctx.groups.filter((g) => g.id !== group.id && g.kind === group.kind && g.samples > 0);

  const onClick = (id: number, e: MouseEvent) =>
    setSelection(select(selection, order, id, { shift: e.shiftKey, toggle: e.metaKey || e.ctrlKey }));

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

  async function dissolve() {
    if (await confirm(`Send all ${group.samples} samples of ${group.code} to Unsure and remove the group?`, "Dissolve"))
      act(() => api.dissolve(bookId, group.id)).then((r) => r && go(`/books/${bookId}/review/unsure`));
  }

  const locked = group.locked;
  return (
    <div>
      {dialog}
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
              disabled={locked || group.status === "labelled"}
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

      <LabelPicker
        bookId={bookId}
        current={{ dev: group.label_dev, guj: group.label_guj }}
        disabled={locked}
        groupId={group.id}
        onSave={async (text) => {
          await act(() => api.label(bookId, group.id, text));
        }}
        onMerge={async (target) => {
          if (await confirm(`Merge ${group.code} (${group.samples} samples) into ${target.code}?`, "Merge")) {
            const r = await act(() => api.merge(bookId, target.id, [group.id]));
            if (r) go(`/books/${bookId}/review/${target.id}`);
          }
        }}
      />
      {locked && <p className="muted small">The group is locked: unlock it to change it.</p>}

      <div className="toolbar row">
        <span className="small muted">{ids.length > 0 ? `${ids.length} selected` : "Click samples to select them"}</span>
        <button disabled={locked || !ids.length} onClick={toUnsure} title="U">
          To Unsure
        </button>
        <button disabled={locked || !ids.length} onClick={toNewGroup} title="N">
          New group
        </button>
        <select
          aria-label="Move selected to group"
          value={moveTo}
          disabled={locked || !ids.length}
          onChange={(e) => setMoveTo(e.target.value)}
        >
          <option value="">Move to group…</option>
          {others.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label_guj ? `${g.label_guj} (${g.code})` : g.code} · {g.samples}
            </option>
          ))}
        </select>
        <button
          disabled={locked || !ids.length || !moveTo}
          onClick={() =>
            act(() => api.move(bookId, ids, Number(moveTo))).then(() => {
              setSelection(emptySelection());
              setMoveTo("");
            })
          }
        >
          Move
        </button>
        <button className="danger" disabled={locked || !ids.length} onClick={remove} title="Delete">
          Delete
        </button>
      </div>

      <SampleGrid samples={samples} selected={selection.ids} onClick={onClick}
        onOpen={(s) => go(`/books/${bookId}/pages/${s.page_id}/${s.id}`)}
      />
      {samples.length < total && (
        <button onClick={more}>
          Show more ({samples.length} of {total})
        </button>
      )}

      <div className="row toolbar">
        <select aria-label="Merge with group" value={mergeWith} disabled={locked} onChange={(e) => setMergeWith(e.target.value)}>
          <option value="">Merge another group into this one…</option>
          {others.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label_guj ? `${g.label_guj} (${g.code})` : g.code} · {g.samples}
            </option>
          ))}
        </select>
        <button
          disabled={locked || !mergeWith}
          onClick={() => act(() => api.merge(bookId, group.id, [Number(mergeWith)])).then(() => setMergeWith(""))}
        >
          Merge
        </button>
        <button className="danger" disabled={locked} onClick={dissolve}>
          Dissolve group
        </button>
      </div>
    </div>
  );
}
