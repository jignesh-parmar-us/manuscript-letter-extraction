// "Review" tab: undo / redo and the label suggestions in a bar on top; the groups of the book on
// the left; the chosen group (or the unsure or deleted samples, or the missing letters) on the
// right. Address: #/books/<id>/review/<group id | unsure | deleted | letters>.
//
// Every change goes through `act()`, which calls the backend, keeps the undo / redo counts and
// reloads the lists. Samples are dragged with @dnd-kit: drop them on a group or on "Unsure".
// Keys: Ctrl/Cmd+Z undo, Shift+Ctrl/Cmd+Z redo; the views add their own keys.
// Label suggestions (C12): the panel in the side bar reads the book with Tesseract; the filters
// "Suggested" and "Mixed readings" use the groups' votes and readings (see Suggestions.tsx).
import { DndContext, DragEndEvent, PointerSensor, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActionResult, api, Book, Group } from "../api";
import ErrorBox from "../components/ErrorBox";
import { emptySelection, Selection } from "../components/selection";
import { useFitHeight } from "../components/useFitHeight";
import { go } from "../route";
import GroupView from "./GroupView";
import SamplesView from "./SamplesView";
import LetterOverview, { missingCount } from "./LetterOverview";
import { isMixed, SuggestPanel } from "./Suggestions";

type Filter = "all" | "unlabelled" | "labelled" | "unreviewed" | "mixed" | "suggested" | "readmixed" | "empty";
type Sort = "code" | "label" | "size" | "spread" | "share";

interface Props {
  book: Book;
  view: string | undefined; // group id, "unsure", "deleted" or "letters" (the letter overview)
  onChanged: () => void;
}

export interface ReviewContext {
  bookId: number;
  version: number; // changes after every action: views reload
  groups: Group[];
  selection: Selection;
  setSelection: (s: Selection) => void;
  act: (run: () => Promise<ActionResult>) => Promise<ActionResult | null>;
}

export default function Review({ book, view, onChanged }: Props) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [version, setVersion] = useState(0);
  const [counts, setCounts] = useState({ undo: book.undo, redo: book.redo });
  const [error, setError] = useState<unknown>(null);
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("label");
  const sidebar = useRef<HTMLElement>(null);
  useFitHeight(sidebar); // the group list scrolls by itself, the window does not

  useEffect(() => {
    api.groups(book.id).then(setGroups, setError);
  }, [book.id, version]);
  useEffect(() => setSelection(emptySelection()), [view]);

  const act = useCallback(
    async (run: () => Promise<ActionResult>) => {
      setError(null);
      try {
        const r = await run();
        setCounts({ undo: r.undo, redo: r.redo });
        setVersion((v) => v + 1);
        onChanged();
        return r;
      } catch (e) {
        setError(e);
        return null;
      }
    },
    [onChanged],
  );

  const undo = useCallback(() => act(() => api.undo(book.id)), [act, book.id]);
  const redo = useCallback(() => act(() => api.redo(book.id)), [act, book.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e)) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // drag and drop: drop a sample (and the other selected ones) on a group or "Unsure"
  const sensors = useDragSensors();
  function onDragEnd(e: DragEndEvent) {
    if (!e.over) return;
    const dragged = Number(String(e.active.id).replace("sample-", ""));
    const ids = selection.ids.has(dragged) ? [...selection.ids] : [dragged];
    const target = String(e.over.id);
    if (target === "unsure") act(() => api.move(book.id, ids, null));
    else if (target.startsWith("group-")) act(() => api.move(book.id, ids, Number(target.slice(6))));
    setSelection(emptySelection());
  }

  const shown = useMemo(() => sortGroups(filterGroups(groups, filter), sort), [groups, filter, sort]);
  const reload = useCallback(() => {
    setVersion((v) => v + 1);
    onChanged();
  }, [onChanged]);
  const chooseFilter = (f: Filter) => {
    setFilter(f);
    if (f === "suggested") setSort("share");
  };
  const current = view && /^\d+$/.test(view) ? groups.find((g) => g.id === Number(view)) : undefined;
  const ctx: ReviewContext = { bookId: book.id, version, groups, selection, setSelection, act };

  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="review-top">
        <div className="row undo-redo">
          <button onClick={undo} disabled={counts.undo === 0} title="Undo (Ctrl/Cmd+Z)">
            ↶ Undo
          </button>
          <button onClick={redo} disabled={counts.redo === 0} title="Redo (Shift+Ctrl/Cmd+Z)">
            ↷ Redo
          </button>
        </div>
        <SuggestPanel book={book} ctx={ctx} onRead={reload} />
      </div>
      <div className="review">
        <aside className="sidebar" ref={sidebar}>
          <SideTarget id="unsure" active={view === "unsure"} onClick={() => go(`/books/${book.id}/review/unsure`)}>
            Unsure <span className="muted">({book.unsure})</span>
          </SideTarget>
          <button
            className={`side-item${view === "deleted" ? " active" : ""}`}
            onClick={() => go(`/books/${book.id}/review/deleted`)}
          >
            Deleted samples
          </button>
          <button
            className={`side-item${view === "letters" ? " active" : ""}`}
            onClick={() => go(`/books/${book.id}/review/letters`)}
            title="Every consonant with every vowel sign, which have a labelled group, and all other labels"
          >
            Letter overview <span className="muted">({missingCount(groups)} missing)</span>
          </button>
          <div className="row small">
            <select aria-label="Show" value={filter} onChange={(e) => chooseFilter(e.target.value as Filter)}>
              <option value="all">All groups</option>
              <option value="unlabelled">Without label</option>
              <option value="labelled">Labelled</option>
              <option value="unreviewed">Not reviewed</option>
              <option value="mixed">Possibly mixed</option>
              <option value="suggested">Suggested</option>
              <option value="readmixed">Mixed readings</option>
              <option value="empty">Empty</option>
            </select>
            <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="label">by label</option>
              <option value="code">by code</option>
              <option value="size">by size</option>
              <option value="spread">by spread</option>
              <option value="share">by suggestion share</option>
            </select>
          </div>
          <div className="side-list" aria-label="Groups">
            {shown.map((g) => (
              <SideTarget
                key={g.id}
                id={`group-${g.id}`}
                active={g.id === current?.id}
                onClick={() => go(`/books/${book.id}/review/${g.id}`)}
              >
                {g.example_image ? <img src={g.example_image} alt="" className="thumb" /> : <span className="thumb" />}
                <span className="side-label">
                  {g.label_guj || g.code}
                  {!g.label_dev && g.suggestion && (
                    <span className="side-suggestion" title={`Suggested: ${g.suggestion.label_guj}`}>
                      {" "}
                      {g.suggestion.label_guj}?
                    </span>
                  )}
                </span>
                <span className="muted small">
                  {g.samples}
                  {g.locked ? " 🔒" : g.status !== "auto" ? " ✓" : ""}
                </span>
              </SideTarget>
            ))}
            {shown.length === 0 && <p className="muted small">No groups.</p>}
          </div>
        </aside>
        <div className="pane">
          {current ? (
            <GroupView key={current.id} group={current} ctx={ctx} />
          ) : view === "letters" ? (
            <LetterOverview ctx={ctx} />
          ) : view === "unsure" || view === "deleted" ? (
            <SamplesView key={view} kind={view} ctx={ctx} />
          ) : (
            <p className="muted">Choose a group on the left, or Unsure.</p>
          )}
        </div>
      </div>
    </DndContext>
  );
}

function SideTarget(props: { id: string; active: boolean; onClick: () => void; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: props.id });
  return (
    <button
      ref={setNodeRef}
      className={`side-item${props.active ? " active" : ""}${isOver ? " over" : ""}`}
      onClick={props.onClick}
    >
      {props.children}
    </button>
  );
}

/** A drag starts only after the pointer moved 6 px, so a plain click still selects a sample. */
export function useDragSensors() {
  return useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
}

export function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

export function filterGroups(groups: Group[], filter: Filter): Group[] {
  if (filter === "all") return groups.filter((g) => g.samples > 0);
  if (filter === "empty") return groups.filter((g) => g.samples === 0);
  if (filter === "unlabelled") return groups.filter((g) => g.samples > 0 && !g.label_dev);
  if (filter === "labelled") return groups.filter((g) => !!g.label_dev);
  if (filter === "unreviewed") return groups.filter((g) => g.samples > 0 && g.status === "auto");
  if (filter === "suggested") return groups.filter((g) => g.samples > 0 && !g.label_dev && !!g.suggestion);
  if (filter === "readmixed") return groups.filter((g) => g.samples > 0 && isMixed(g));
  // possibly mixed: the 20% of groups (at least one) whose samples are furthest from their centre
  const candidates = groups.filter((g) => g.samples > 1 && g.spread !== null);
  const spreads = candidates.map((g) => g.spread as number).sort((a, b) => a - b);
  const limit = spreads[Math.max(0, Math.ceil(0.8 * spreads.length) - 1)] ?? 0;
  return candidates.filter((g) => (g.spread as number) >= limit);
}

/** Plain code point order (not the language's collation). */
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

export function sortGroups(groups: Group[], sort: Sort): Group[] {
  const out = [...groups];
  if (sort === "size") out.sort((a, b) => b.samples - a.samples);
  else if (sort === "spread") out.sort((a, b) => (b.spread ?? 0) - (a.spread ?? 0));
  else if (sort === "share")
    out.sort((a, b) => (b.suggestion?.share ?? -1) - (a.suggestion?.share ?? -1) || b.samples - a.samples);
  else if (sort === "label")
    // labelled groups in Unicode code point order of the label (the letter order of the script),
    // then the unlabelled ones by code
    out.sort((a, b) =>
      a.label_dev && b.label_dev
        ? cmp(a.label_dev, b.label_dev) || cmp(a.code, b.code)
        : a.label_dev
          ? -1
          : b.label_dev
            ? 1
            : cmp(a.code, b.code),
    );
  else out.sort((a, b) => a.code.localeCompare(b.code));
  return out;
}
