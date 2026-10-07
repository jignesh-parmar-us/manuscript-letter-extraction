// "Pages" tab: a page with a box around every sample, to fix wrong cuts quickly (FR-8).
// Address: #/books/<id>/pages/<page id>[/<sample id>]; with a sample id, that sample is selected and
// scrolled into view with a flashing ring around it (double-click on a letter in Review opens it here);
// the ring goes when another box is clicked. Opened that way, "← Back to …" returns to that letter in
// the Review tab, after any number of changes here (returnSpot.ts).
//   Select   click a box (Shift or Ctrl/Cmd+click for more); Join, Delete, Open its group, and put the
//            selection in a group (Label, Move to group, New group, To Unsure) without leaving the page
//   Draw     drag a box around ink the cutting missed: it becomes a new (unsure) sample
//   Split    click inside the selected sample where it should be cut in two
// Boxes are coloured by group; unsure samples have a dashed grey box.
// The page is chosen in a dialog (PagePicker.tsx: all pages, with a search box), so the page has the
// whole width. The page and the selection panel under it fill exactly the rest of the window, so the
// page scrolls by itself to its very bottom, and the panel never covers it; after a change (delete, join, split, move, label, new box) a dashed
// marker stays on that spot until the next click, so the place is easy to find again.
import { ChangeEvent, MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, Book, fileToBase64, Group, PageDetail, PageInfo, Sample } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import LabelPicker from "../components/LabelPicker";
import { backTo, goBack } from "../components/returnSpot";
import { useFitHeight } from "../components/useFitHeight";
import { go } from "../route";
import GroupPicker, { MoveTarget } from "./GroupPicker";
import PagePicker from "./PagePicker";

type Mode = "select" | "draw" | "split";
type Box = [number, number, number, number];

interface Props {
  book: Book;
  pageId: number | null;
  sampleId?: number | null; // select this sample and scroll to it
  onChanged: () => void;
}

/** A stable colour per group, so neighbouring letters of different groups look different. */
export function groupColour(groupId: number | null): string {
  if (groupId === null) return "#888";
  return `hsl(${(groupId * 137.508) % 360} 70% 42%)`;
}

export default function PageViewer({ book, pageId, sampleId = null, onChanged }: Props) {
  const [pages, setPages] = useState<PageInfo[]>([]);
  const [page, setPage] = useState<PageDetail | null>(null);
  const [groups, setGroups] = useState<Map<number, Group>>(new Map());
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<Mode>("select");
  const [zoom, setZoom] = useState(0.5);
  const [drawing, setDrawing] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [message, setMessage] = useState<string>("");
  const [offer, setOffer] = useState<number[]>([]);
  const [picking, setPicking] = useState(false); // the "Move to…" picker is open
  const [lastSpot, setLastSpot] = useState<Box | null>(null); // where the last change was
  const [focusId, setFocusId] = useState<number | null>(null); // the sample with the ring
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const [dialog, confirm] = useConfirm();
  const svgRef = useRef<SVGSVGElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLDivElement>(null);
  // the page and the selection panel fill the rest of the window; fitted again once the page is there
  useFitHeight(area, 8, "height", page?.id ?? null);
  const [choosing, setChoosing] = useState(false);
  const back = backTo(book.id); // opened from a letter in the Review tab: the way back to it // the page picker is open
  const shown = useRef<string>(""); // the page/sample already scrolled to, so reloads do not scroll again

  useEffect(() => {
    api.pages(book.id).then(setPages, setError);
  }, [book.id, version]);
  useEffect(() => {
    api.groups(book.id).then((gs) => setGroups(new Map(gs.map((g) => [g.id, g]))), setError);
  }, [book.id, version]);
  useEffect(() => {
    if (pageId === null) {
      setPage(null);
      return;
    }
    api.page(pageId).then(setPage, setError);
  }, [pageId, version]);
  useEffect(() => {
    setSelected(new Set());
    setOffer([]);
    setMessage("");
    setFocusId(null);
    setLastSpot(null);
  }, [pageId]);
  // Opened for one sample: select it and bring it to the middle of the view, once.
  useEffect(() => {
    const key = `${pageId}/${sampleId}`;
    if (!page || page.id !== pageId || sampleId === null || shown.current === key) return;
    const s = page.samples.find((x) => x.id === sampleId);
    if (!s) return;
    shown.current = key;
    setSelected(new Set([s.id]));
    setFocusId(s.id);
    // after the selection panel has opened under the page (it takes room), bring the sample to the middle
    const centre = () => {
      const box = scrollRef.current;
      box?.scrollTo?.({
        left: (s.box[0] + s.box[2] / 2) * zoom - box.clientWidth / 2,
        top: (s.box[1] + s.box[3] / 2) * zoom - box.clientHeight / 2,
      });
    };
    centre();
    window.requestAnimationFrame?.(() => window.requestAnimationFrame(centre));
  }, [page, pageId, sampleId, zoom]);

  /** Run an action, then reload the page and the book's numbers. */
  const act = useCallback(
    async <T,>(run: () => Promise<T>): Promise<T | null> => {
      setError(null);
      try {
        const r = await run();
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

  /** Page coordinates of a mouse event on the page. */
  function toPage(e: MouseEvent): [number, number] {
    const rect = svgRef.current!.getBoundingClientRect();
    const scale = page!.width / rect.width;
    return [Math.round((e.clientX - rect.left) * scale), Math.round((e.clientY - rect.top) * scale)];
  }

  /** The box around these samples (page coordinates). */
  function around(ids: Iterable<number>): Box | null {
    const boxes = (page?.samples ?? []).filter((x) => new Set(ids).has(x.id)).map((x) => x.box);
    if (!boxes.length) return null;
    const x0 = Math.min(...boxes.map((b) => b[0]));
    const y0 = Math.min(...boxes.map((b) => b[1]));
    const x1 = Math.max(...boxes.map((b) => b[0] + b[2]));
    const y1 = Math.max(...boxes.map((b) => b[1] + b[3]));
    return [x0, y0, x1 - x0, y1 - y0];
  }

  function clickBox(s: Sample, e: MouseEvent) {
    e.stopPropagation();
    setFocusId(null);
    setLastSpot(null);
    if (mode === "split") {
      if (selected.size === 1 && selected.has(s.id)) split(s, toPage(e)[0]);
      return;
    }
    if (mode !== "select") return;
    const next = e.shiftKey || e.metaKey || e.ctrlKey ? new Set(selected) : new Set<number>();
    if (next.has(s.id)) next.delete(s.id);
    else next.add(s.id);
    setSelected(next);
  }

  async function split(s: Sample, x: number) {
    setLastSpot(s.box);
    const r = await act(() => api.split(book.id, s.id, x));
    if (r) {
      setSelected(new Set());
      setMode("select");
      setMessage("Split into two samples (both unsure).");
    }
  }

  function down(e: MouseEvent) {
    if (mode !== "draw" || !page) return;
    const [x, y] = toPage(e);
    setDrawing({ x0: x, y0: y, x1: x, y1: y });
  }
  function move(e: MouseEvent) {
    if (!drawing) return;
    const [x, y] = toPage(e);
    setDrawing({ ...drawing, x1: x, y1: y });
  }
  async function up() {
    if (!drawing || !page) return;
    const box: Box = [
      Math.min(drawing.x0, drawing.x1),
      Math.min(drawing.y0, drawing.y1),
      Math.abs(drawing.x1 - drawing.x0),
      Math.abs(drawing.y1 - drawing.y0),
    ];
    setDrawing(null);
    setLastSpot(box);
    const r = await act(() => api.crop(book.id, page.id, box));
    if (r) {
      setOffer(r.overlapping ?? []);
      setMessage("New sample made from the box (unsure).");
      if (r.sample) setSelected(new Set([r.sample.id]));
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const r = await act(async () => api.upload(book.id, file.name, await fileToBase64(file)));
    if (r) setMessage(`${file.name} was added as an unsure sample (see Review groups → Unsure).`);
  }

  async function removeSelected() {
    if (await confirm(`Delete ${selected.size} sample(s)? Deleted samples can be restored.`, "Delete")) {
      setLastSpot(around(selected));
      await act(() => api.deleteSamples(book.id, [...selected]));
      setSelected(new Set());
    }
  }

  /** Put the selected samples in a group (null: Unsure), or in a new group of their own. */
  async function regroup(groupId: number | null | "new") {
    const ids = [...selected];
    setLastSpot(around(ids));
    const r = await act(() => (groupId === "new" ? api.newGroup(book.id, ids) : api.move(book.id, ids, groupId)));
    if (r) {
      const g = groupId === "new" ? null : groupId === null ? null : groups.get(groupId);
      setMessage(
        groupId === "new"
          ? `${ids.length} sample(s) put in a new group.`
          : groupId === null
            ? `${ids.length} sample(s) moved to Unsure.`
            : `${ids.length} sample(s) moved to ${g ? g.label_guj || g.code : "the group"}.`,
      );
    }
  }

  /** Give the selected samples a label: move them to the group with that label (the largest
   *  unlocked one, if several), or to a new group that gets the label. One label, one group: if only
   *  a locked group has it, nothing is done (the picker says so). */
  async function labelSelected(text: string): Promise<boolean> {
    const ids = [...selected];
    setLastSpot(around(ids));
    const info = await api.checkLabel(text, book.id).catch((e) => {
      setError(e);
      return null;
    });
    if (!info?.ok || !info.devanagari) return false;
    const users = info.used_by ?? [];
    const into = users.filter((g) => !g.locked).sort((a, b) => b.samples - a.samples)[0];
    if (into) {
      if (!(await act(() => api.move(book.id, ids, into.id)))) return false;
      setMessage(`${ids.length} sample(s) moved to the group ${info.gujarati} (${into.code}).`);
      return true;
    }
    if (users.length) {
      setError(new Error(`The group ${users[0].code} with the label ${info.gujarati} is locked; unlock it first.`));
      return false;
    }
    const made = await act(() => api.newGroup(book.id, ids));
    if (!made?.group_id || !(await act(() => api.label(book.id, made.group_id!, text)))) return false;
    setMessage(`${ids.length} sample(s) put in a new group labelled ${info.gujarati}.`);
    return true;
  }

  /** From the "Move to…" picker: into a group, or under a label (its group, or a new one). */
  async function moveTo(target: MoveTarget) {
    setPicking(false);
    const ids = [...selected];
    if ("groupId" in target) return regroup(target.groupId);
    setLastSpot(around(ids));
    if (await act(() => api.labelSamples(book.id, ids, target.label)))
      setMessage(`${ids.length} sample(s) put under the label ${target.label}.`);
  }

  const sel = page?.samples.filter((s) => selected.has(s.id)) ?? [];
  const current = pages.find((p) => p.id === pageId);
  const at = current ? pages.indexOf(current) : -1;
  const prev = at > 0 ? pages[at - 1] : undefined;
  const next = at >= 0 && at < pages.length - 1 ? pages[at + 1] : undefined;
  const single = sel.length === 1 ? sel[0] : null;
  const singleGroup = single?.group_id ? groups.get(single.group_id) : undefined;

  return (
    <div className="pages-tab">
      {dialog}
      {choosing && (
        <PagePicker
          pages={pages}
          currentId={pageId}
          onPick={(p) => {
            setChoosing(false);
            go(`/books/${book.id}/pages/${p.id}`);
          }}
          onClose={() => setChoosing(false)}
        />
      )}
      {picking && (
        <GroupPicker groups={[...groups.values()]} count={selected.size} onPick={moveTo} onClose={() => setPicking(false)} />
      )}
      <div className="pane">
        <ErrorBox error={error} onClose={() => setError(null)} />
        <div className="row page-nav">
          {back && (
            <button className="back" onClick={goBack} title="Back to the letter you opened, where you were in the Review tab">
              ← Back to {back.label}
            </button>
          )}
          <button disabled={!prev} onClick={() => prev && go(`/books/${book.id}/pages/${prev.id}`)} aria-label="Previous page" title="Previous page">
            ◀
          </button>
          <button className="page-choose" onClick={() => setChoosing(true)} title="Choose a page">
            {current ? `${current.file}` : "Choose a page"}{" "}
            <span className="muted small">
              {current ? `${pages.indexOf(current) + 1} of ${pages.length}` : `${pages.length} pages`} ▾
            </span>
          </button>
          <button disabled={!next} onClick={() => next && go(`/books/${book.id}/pages/${next.id}`)} aria-label="Next page" title="Next page">
            ▶
          </button>
          <label className="button upload">
            Upload letter image…
            <input type="file" accept="image/*" onChange={upload} hidden />
          </label>
        </div>
        {!page ? (
          <p className="muted">Choose a page: the button above lists all pages, with a search box.</p>
        ) : (
          <>
            <div className="toolbar row">
              <div className="row" role="group" aria-label="Tool">
                {(["select", "draw", "split"] as Mode[]).map((m) => (
                  <button
                    key={m}
                    className={mode === m ? "tab active" : "tab"}
                    disabled={m === "split" && !single}
                    onClick={() => setMode(m)}
                  >
                    {m === "select" ? "Select" : m === "draw" ? "Draw a box" : "Split"}
                  </button>
                ))}
              </div>
              <button
                disabled={sel.length < 2}
                onClick={() => {
                  setLastSpot(around(selected));
                  act(() => api.join(book.id, [...selected])).then((r) => r?.sample && setSelected(new Set([r.sample.id])));
                }}
              >
                Join ({sel.length})
              </button>
              <button className="danger" disabled={sel.length === 0} onClick={removeSelected}>
                Delete
              </button>
              <button onClick={() => act(() => api.undo(book.id))}>↶ Undo</button>
              <button onClick={() => act(() => api.redo(book.id))}>↷ Redo</button>
              <select className="narrow" aria-label="Zoom" value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
                {[0.25, 0.35, 0.5, 0.75, 1].map((z) => (
                  <option key={z} value={z}>
                    {Math.round(z * 100)}%
                  </option>
                ))}
              </select>
            </div>
            <p className="muted small">
              {mode === "draw"
                ? "Drag a box around ink that should be one letter."
                : mode === "split"
                  ? "Click inside the selected sample where it should be cut."
                  : "Click a box to select it; Shift or Ctrl/Cmd+click to select more."}{" "}
              {message}
            </p>
            <div className="page-area" ref={area}>
            <div className="page-scroll" ref={scrollRef}>
            <div className="page-canvas" style={{ width: page.width * zoom, height: page.height * zoom }}>
              <img
                src={page.image}
                alt={page.file}
                width={page.width * zoom}
                height={page.height * zoom}
                draggable={false}
              />
              <svg
                ref={svgRef}
                viewBox={`0 0 ${page.width} ${page.height}`}
                className={`overlay mode-${mode}`}
                aria-label="Samples on the page"
                onMouseDown={down}
                onMouseMove={move}
                onMouseUp={up}
              >
                {page.samples.map((s) => (
                  <rect
                    key={s.id}
                    data-testid={`box-${s.id}`}
                    x={s.box[0]}
                    y={s.box[1]}
                    width={s.box[2]}
                    height={s.box[3]}
                    className={`box${selected.has(s.id) ? " selected" : ""}${s.group_id === null ? " unsure" : ""}`}
                    stroke={groupColour(s.group_id)}
                    onClick={(e) => clickBox(s, e)}
                  >
                    <title>{s.group_id ? groups.get(s.group_id)?.label_guj || groups.get(s.group_id)?.code : "unsure"}</title>
                  </rect>
                ))}
                {lastSpot && (
                  <rect
                    className="last-spot"
                    data-testid="last-spot"
                    x={lastSpot[0] - 8}
                    y={lastSpot[1] - 8}
                    width={lastSpot[2] + 16}
                    height={lastSpot[3] + 16}
                    rx={8}
                  >
                    <title>The last change was here</title>
                  </rect>
                )}
                {(() => {
                  const f = focusId !== null ? page.samples.find((x) => x.id === focusId) : undefined;
                  if (!f) return null;
                  const pad = Math.max(12, Math.round(f.box[3] * 0.35)); // bigger than the box, so it stands out
                  return (
                    <rect
                      key={f.id} // a new sample restarts the flashing
                      className="focus-ring"
                      data-testid="focus-ring"
                      x={f.box[0] - pad}
                      y={f.box[1] - pad}
                      width={f.box[2] + 2 * pad}
                      height={f.box[3] + 2 * pad}
                      rx={pad}
                    />
                  );
                })()}
                {drawing && (
                  <rect
                    className="drawing"
                    x={Math.min(drawing.x0, drawing.x1)}
                    y={Math.min(drawing.y0, drawing.y1)}
                    width={Math.abs(drawing.x1 - drawing.x0)}
                    height={Math.abs(drawing.y1 - drawing.y0)}
                  />
                )}
              </svg>
            </div>
            <div className="page-room" aria-hidden="true" />
            </div>
            {(offer.length > 0 || sel.length > 0) && (
              <div className="selection-dock" aria-label="Selection">
            {offer.length > 0 && (
              <div className="card subtle row">
                <span className="small">The new sample overlaps {offer.length} sample(s).</span>
                <button
                  onClick={async () => {
                    await act(() => api.deleteSamples(book.id, offer));
                    setOffer([]);
                  }}
                >
                  Delete them
                </button>
                <button onClick={() => setOffer([])}>Keep them</button>
              </div>
            )}
            {sel.length > 0 && (
              <div className="card row" aria-label="Selected samples">
                {sel.slice(0, 5).map((s) => (
                  <img key={s.id} src={s.image} alt={`selected sample ${s.id}`} className="selected-sample" />
                ))}
                {sel.length > 5 && <span className="muted small">+{sel.length - 5}</span>}
                {single ? (
                  <span className="small">
                    {single.source !== "auto" && <span className="badge ok">{single.source}</span>} line {single.line} ·{" "}
                    {singleGroup ? `group ${singleGroup.label_guj || singleGroup.code}` : "unsure"}
                  </span>
                ) : (
                  <span className="small">{sel.length} selected</span>
                )}
                {singleGroup && (
                  <button onClick={() => go(`/books/${book.id}/review/${singleGroup.id}`)}>Open group</button>
                )}
                <button onClick={() => setPicking(true)} title="Move to a letter's group or another group">
                  Move to…
                </button>
                <button onClick={() => regroup("new")}>New group</button>
                <button disabled={sel.every((s) => s.group_id === null)} onClick={() => regroup(null)}>
                  To Unsure
                </button>
                <div className="selected-label" title="Moves the selected samples to the group with this label, or to a new group with it">
                  <LabelPicker
                    bookId={book.id}
                    current={{
                      dev: singleGroup?.label_dev ?? "",
                      guj: singleGroup?.label_guj ?? "",
                    }}
                    saveText={`Label ${sel.length === 1 ? "it" : `these ${sel.length}`}`}
                    canClear={false}
                    compact
                    onSave={labelSelected}
                  />
                </div>
              </div>
            )}
              </div>
            )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
