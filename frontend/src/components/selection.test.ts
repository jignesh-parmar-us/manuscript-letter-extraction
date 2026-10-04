import { describe, expect, it } from "vitest";
import { emptySelection, select } from "./selection";

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
});
