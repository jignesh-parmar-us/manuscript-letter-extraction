import { describe, expect, it } from "vitest";
import { arrowTarget, Box, cursorOf, emptySelection, moveTo, select } from "./selection";

const order = [10, 11, 12, 13, 14];
const ids = (s: { ids: Set<number> }) => [...s.ids].sort();

describe("selection", () => {
  it("click selects only that sample", () => {
    let s = select(emptySelection(), order, 11, {});
    s = select(s, order, 13, {});
    expect(ids(s)).toEqual([13]);
  });
  it("Ctrl/Cmd+click adds and removes", () => {
    let s = select(emptySelection(), order, 11, {});
    s = select(s, order, 13, { toggle: true });
    expect(ids(s)).toEqual([11, 13]);
    s = select(s, order, 11, { toggle: true });
    expect(ids(s)).toEqual([13]);
  });
  it("Shift+click selects a range in either direction", () => {
    let s = select(emptySelection(), order, 13, {});
    s = select(s, order, 11, { shift: true });
    expect(ids(s)).toEqual([11, 12, 13]);
    s = select(s, order, 14, { shift: true });
    expect(ids(s)).toEqual([13, 14]);
  });

  // tiles of different widths in two rows: 10 11 12 (top 0) / 13 14 (top 50)
  const boxes: Box[] = [
    { left: 0, top: 0, width: 40, height: 40 },
    { left: 46, top: 0, width: 80, height: 40 },
    { left: 132, top: 0, width: 40, height: 40 },
    { left: 0, top: 50, width: 100, height: 40 },
    { left: 106, top: 50, width: 40, height: 40 },
  ];
  it("arrows: ← → go to the previous / next sample and stop at the ends", () => {
    expect(arrowTarget(order, boxes, 11, "right")).toBe(12);
    expect(arrowTarget(order, boxes, 12, "right")).toBe(13); // the next row
    expect(arrowTarget(order, boxes, 14, "right")).toBe(14);
    expect(arrowTarget(order, boxes, 10, "left")).toBe(10);
  });
  it("arrows: ↑ ↓ go to the nearest tile in the row above / below", () => {
    expect(arrowTarget(order, boxes, 12, "down")).toBe(14);  // centre 152 is nearest 14's (126)
    expect(arrowTarget(order, boxes, 10, "down")).toBe(13);
    expect(arrowTarget(order, boxes, 13, "up")).toBe(10);    // centre 50 is nearest 10's (20)
    expect(arrowTarget(order, boxes, 14, "up")).toBe(12);    // centre 126 is nearest 12's (152)
    expect(arrowTarget(order, boxes, 13, "down")).toBe(13);  // no row below
    expect(arrowTarget(order, boxes, 11, "up")).toBe(11);
  });
  it("arrows: with nothing to start from they go to the first sample", () => {
    expect(arrowTarget(order, boxes, null, "up")).toBe(10);
    expect(arrowTarget([], [], null, "down")).toBeNull();
  });
  it("arrows start from the last clicked or moved-to sample, and Shift extends from the anchor", () => {
    let s = select(emptySelection(), order, 11, {});
    expect(cursorOf(s, order)).toBe(11);
    s = moveTo(s, order, 12, true);
    s = moveTo(s, order, 13, true);
    expect(ids(s)).toEqual([11, 12, 13]);
    expect(cursorOf(s, order)).toBe(13);
    s = moveTo(s, order, 10, true);                           // back past the anchor
    expect(ids(s)).toEqual([10, 11]);
    s = moveTo(s, order, 14, false);
    expect(ids(s)).toEqual([14]);
    expect(cursorOf({ ids: new Set([12, 10]), anchor: null }, order)).toBe(12);
  });
});
