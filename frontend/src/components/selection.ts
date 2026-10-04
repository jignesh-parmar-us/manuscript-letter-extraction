// Selecting samples in a grid, as in a file manager:
//   click          only this sample
//   Ctrl/Cmd+click add or remove this sample
//   Shift+click    everything from the last clicked sample to this one
export interface Selection {
  ids: Set<number>;
  anchor: number | null; // the last sample clicked without Shift
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
    return { ids, anchor: current.anchor };
  }
  if (mods.toggle) {
    const ids = new Set(current.ids);
    if (ids.has(clicked)) ids.delete(clicked);
    else ids.add(clicked);
    return { ids, anchor: clicked };
  }
  return { ids: new Set([clicked]), anchor: clicked };
}
