// The page manager (C22) of a book (in Prepare) and of a dataset (in Pages & capture): the pages in their order,
// with a thumbnail and what is on each; ▲ / ▼ or dragging a row by its handle ⠿ (C25) change the order, Exclude keeps a page but skips it (a book: Prepare,
// reading, Measure, export; a dataset: capture, training, export), Delete removes it. Both ask first when a page has
// checked lines, corrections or letters in reviewed groups (app/pages.py).
import { DragEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { api, ApiError, Kind, PageEntry, PageList } from "../api";
import { useConfirm } from "./Confirm";

interface Props {
  bookId: number;
  kind: Kind;
  busy?: boolean;            // a job is running: nothing can be changed
  reload?: number;           // changes when the pages may have changed (a job ended)
  onChanged: () => void;
  onError: (e: unknown) => void;
  actions?: (p: PageEntry) => ReactNode;   // more buttons for a prepared page (Open, Prepare again…)
}

const THUMBS_KEY = "page-manager-thumbs";
const DRAG_TYPE = "application/x-page-id";

/** How many places a page at `from` moves when it is dropped before (or after) the page at `onto`, both places
 *  among the pages with a row: the `by` of POST …/pages/{id}/move. */
export function dropMove(from: number, onto: number, after: boolean): number {
  let to = onto + (after ? 1 : 0);
  if (from < to) to -= 1;
  return to - from;
}

function readThumbs(): boolean {
  try {
    return localStorage.getItem(THUMBS_KEY) !== "off";
  } catch {
    return true;
  }
}

export default function PageManager({ bookId, kind, busy = false, reload = 0, onChanged, onError, actions }: Props) {
  const [list, setList] = useState<PageList | null>(null);
  const [thumbs, setThumbs] = useState(readThumbs);
  const [working, setWorking] = useState(false);
  const [dragged, setDragged] = useState<number | null>(null);     // place of the page being dragged
  const [target, setTarget] = useState<{ at: number; after: boolean } | null>(null);
  const [dialog, confirm] = useConfirm();
  const prepared = kind === "book" ? "Prepared" : "Captured";

  const load = useCallback(() => {
    api.pageList(bookId).then(setList, onError);
  }, [bookId, onError]);
  useEffect(load, [load, reload]);

  function showThumbs(on: boolean) {
    setThumbs(on);
    try {
      localStorage.setItem(THUMBS_KEY, on ? "on" : "off");
    } catch {
      // the choice is only not remembered
    }
  }

  /** Run a change; when the backend asks first (something is lost or left unused), ask, then repeat with force. */
  async function change(run: (force: boolean) => Promise<unknown>, question: string, button: string) {
    setWorking(true);
    try {
      try {
        await run(false);
      } catch (e) {
        if (!(e instanceof ApiError && e.needsConfirmation)) throw e;
        if (!(await confirm(`${e.message} ${question}`, button))) return;
        await run(true);
      }
      load();
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setWorking(false);
    }
  }

  async function remove(p: PageEntry) {
    const what = list?.owned
      ? "Its image is removed from the app."
      : "Its image stays in your folder; the page stays here, excluded.";
    const lost = p.prepared ? ` Its ${kind === "book" ? "lines, readings and text" : "letters and lines"} go too.` : "";
    if (!(await confirm(`Delete page ${p.file}? ${what}${lost}`, "Delete"))) return;
    await change((force) => api.deletePage(bookId, p.file, force), "Delete it anyway?", "Delete");
  }

  /** Whether the pointer is in the lower half of the row (the page lands after it). */
  function lowerHalf(e: DragEvent<HTMLTableRowElement>): boolean {
    const box = e.currentTarget.getBoundingClientRect();
    return (e.clientY ?? 0) > box.top + box.height / 2;
  }

  function dragOver(e: DragEvent<HTMLTableRowElement>, at: number) {
    if (dragged === null || at < 0) return;
    e.preventDefault();
    const after = lowerHalf(e);
    if (target?.at !== at || target.after !== after) setTarget({ at, after });
  }

  function drop(e: DragEvent<HTMLTableRowElement>, at: number) {
    if (dragged === null || at < 0 || !list) return;
    e.preventDefault();
    const by = dropMove(dragged, at, lowerHalf(e));
    const id = list.pages.filter((p) => p.id !== null)[dragged]?.id;
    setDragged(null);
    setTarget(null);
    if (by && id != null) change(() => api.movePage(bookId, id, by), "", "");
  }

  if (!list) return null;
  if (!list.pages.length) return <p className="muted small">No pages yet.</p>;
  const ordered = list.pages.filter((p) => p.id !== null);
  const locked = busy || working;
  const included = list.pages.filter((p) => !p.excluded).length;
  const place = new Map(ordered.filter((p) => !p.excluded).map((p, i) => [p.id, i + 1]));   // as read and exported

  return (
    <div className="page-manager">
      {dialog}
      <div className="row small">
        <strong>Pages</strong>
        <span className="muted">
          {included} of {list.pages.length} used{list.pages.length > included && ", the others excluded"}
        </span>
        <label className="row">
          <input type="checkbox" checked={thumbs} onChange={(e) => showThumbs(e.target.checked)} />
          Thumbnails
        </label>
      </div>
      <table className="list" aria-label="Pages">
        <thead>
          <tr>
            <th className="num">#</th>
            {thumbs && <th />}
            <th>Page</th>
            <th>Status</th>
            <th className="num">Lines</th>
            <th className="num">Letters</th>
            <th>Checked / reviewed</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.pages.map((p) => {
            const at = p.id === null ? -1 : ordered.findIndex((o) => o.id === p.id);
            return (
              <tr key={p.file}
                className={[p.excluded && "excluded", at === dragged && "dragged",
                  target?.at === at && at !== dragged && (target.after ? "drop-after" : "drop-before")]
                  .filter(Boolean).join(" ") || undefined}
                onDragOver={(e) => dragOver(e, at)}
                onDrop={(e) => drop(e, at)}>
                <td className="num">{place.get(p.id) ?? ""}</td>
                {thumbs && (
                  <td>
                    <img className="page-thumb" src={p.thumb} alt="" loading="lazy" />
                  </td>
                )}
                <td>
                  {p.file}
                  {p.missing && <div className="small warn-text">the image file is missing</div>}
                </td>
                <td>
                  {p.excluded ? (
                    <span className="badge warn">Excluded</span>
                  ) : p.prepared ? (
                    <span className={p.status === "OK" ? "badge ok" : "badge warn"}>{p.status === "OK" ? prepared : p.status}</span>
                  ) : (
                    <span className="badge">Not {prepared.toLowerCase()} yet</span>
                  )}{" "}
                  <span className="muted small">{p.message}</span>
                </td>
                <td className="num">{p.prepared ? p.lines : ""}</td>
                <td className="num">{p.prepared ? p.samples : ""}</td>
                <td className="small">
                  {[p.checked && `${p.checked} checked`, p.corrections && `${p.corrections} corrected`,
                    p.reviewed && `${p.reviewed} reviewed`].filter(Boolean).join(", ")}
                </td>
                <td className="actions">
                  {p.id !== null && (
                    <>
                      <span className={`drag-handle${locked ? " off" : ""}`} draggable={!locked}
                        aria-label={`Drag ${p.file} to another place`} title="Drag to another place"
                        onDragStart={(e) => {
                          e.dataTransfer?.setData(DRAG_TYPE, String(p.id));
                          if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
                          setDragged(at);
                        }}
                        onDragEnd={() => {
                          setDragged(null);
                          setTarget(null);
                        }}>
                        ⠿
                      </span>
                      <button aria-label={`Move ${p.file} up`} title="Up" disabled={locked || at === 0}
                        onClick={() => change(() => api.movePage(bookId, p.id!, -1), "", "")}>
                        ▲
                      </button>
                      <button aria-label={`Move ${p.file} down`} title="Down" disabled={locked || at === ordered.length - 1}
                        onClick={() => change(() => api.movePage(bookId, p.id!, 1), "", "")}>
                        ▼
                      </button>
                    </>
                  )}
                  <button disabled={locked}
                    onClick={() => change((force) => api.excludePage(bookId, p.file, !p.excluded, force),
                      "Exclude it anyway?", "Exclude")}>
                    {p.excluded ? "Include" : "Exclude"}
                  </button>
                  <button className="danger" disabled={locked} onClick={() => remove(p)}>
                    Delete
                  </button>
                  {p.prepared && !p.excluded && actions?.(p)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
