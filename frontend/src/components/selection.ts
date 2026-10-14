// Selecting samples in a grid, as in a file manager:
//   click          only this sample
//   Ctrl/Cmd+click add or remove this sample
//   Shift+click    everything from the last clicked sample to this one
//   ← → ↑ ↓        move to the next sample (↑ ↓: the one above / below on screen); with Shift, extend
export interface Selection {
  ids: Set<number>;
  anchor: number | null; // the last sample clicked without Shift
  cursor?: number | null; // the sample the arrow keys move from (the last one clicked or moved to)
}

export const emptySelection = (): Selection => ({ ids: new Set(), anchor: null });

export function select(
  current: Selection,
  order: number[],
  clicked: number,
  mods: { shift?: boolean; toggle?: boolean },
): Selection {
  if (mods.shift && current.anchor !== null && order.includes(current.anchor)) {
    const a = order.indexOf(current.anchor);
    const b = order.indexOf(clicked);
    const [from, to] = a <= b ? [a, b] : [b, a];
    const ids = new Set(mods.toggle ? current.ids : []);
    order.slice(from, to + 1).forEach((id) => ids.add(id));
    return { ids, anchor: current.anchor, cursor: clicked };
  }
  if (mods.toggle) {
    const ids = new Set(current.ids);
    if (ids.has(clicked)) ids.delete(clicked);
    else ids.add(clicked);
    return { ids, anchor: clicked, cursor: clicked };
  }
  return { ids: new Set([clicked]), anchor: clicked, cursor: clicked };
}

export type Arrow = "left" | "right" | "up" | "down";
export const ARROWS: Record<string, Arrow> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Where the arrow keys start from: the cursor, else the anchor, else the last selected sample; null if none. */
export function cursorOf(current: Selection, order: number[]): number | null {
  for (const id of [current.cursor, current.anchor]) if (id != null && order.includes(id)) return id;
  const chosen = order.filter((id) => current.ids.has(id));
  return chosen.length ? chosen[chosen.length - 1] : null;
}

/** The sample an arrow key goes to from `from` (an index in `order`; `boxes` are the tiles on screen, same order).
 *  ← → the previous / next sample; ↑ ↓ the nearest sample in the row above / below (the tiles wrap and need not
 *  be the same width). It stays put at the edges. Without a sample to start from, any arrow goes to the first. */
export function arrowTarget(order: number[], boxes: Box[], from: number | null, arrow: Arrow): number | null {
  if (!order.length) return null;
  const i = from === null ? -1 : order.indexOf(from);
  if (i < 0) return order[0];
  if (arrow === "left") return order[Math.max(0, i - 1)];
  if (arrow === "right") return order[Math.min(order.length - 1, i + 1)];
  const me = boxes[i];
  if (!me) return order[i];
  const middle = (b: Box) => b.top + b.height / 2;
  const centre = me.left + me.width / 2;
  const others = boxes
    .map((b, j) => ({ b, j }))
    .filter(({ b }) => (arrow === "down" ? b.top >= me.top + me.height / 2 : middle(b) <= me.top));
  if (!others.length) return order[i];
  // the nearest row in that direction, then the tile in it whose centre is closest to this one's
  const rowTop = arrow === "down" ? Math.min(...others.map(({ b }) => b.top)) : Math.max(...others.map(({ b }) => b.top));
  const row = others.filter(({ b }) => Math.abs(b.top - rowTop) < me.height / 2);
  const best = row.reduce((a, c) =>
    Math.abs(c.b.left + c.b.width / 2 - centre) < Math.abs(a.b.left + a.b.width / 2 - centre) ? c : a,
  );
  return order[best.j];
}

/** Select `to` after an arrow key: only it, or with `extend` (Shift) everything from the anchor to it. */
export function moveTo(current: Selection, order: number[], to: number, extend: boolean): Selection {
  if (extend) {
    const anchor = current.anchor !== null && order.includes(current.anchor) ? current.anchor : cursorOf(current, order) ?? to;
    const a = order.indexOf(anchor);
    const b = order.indexOf(to);
    const [from, last] = a <= b ? [a, b] : [b, a];
    return { ids: new Set(order.slice(from, last + 1)), anchor, cursor: to };
  }
  return { ids: new Set([to]), anchor: to, cursor: to };
}
