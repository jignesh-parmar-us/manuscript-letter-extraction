import { afterEach, describe, expect, it, vi } from "vitest";
import { matchScale } from "./ScriptTabs";

/** A canvas whose letters are `tall` px high in the custom face and 70 px in the normal fonts. */
function fakeCanvas(tall: number) {
  let font = "";
  const ctx = {
    set font(f: string) { font = f; },
    get font() { return font; },
    measureText: () => (font.includes("my-face") ? { actualBoundingBoxAscent: tall, actualBoundingBoxDescent: 0 }
      : { actualBoundingBoxAscent: 60, actualBoundingBoxDescent: 10 }),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as never);
}

describe("matchScale (custom fonts)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("scales a font whose letters are drawn smaller up to the normal fonts' size", () => {
    fakeCanvas(56);
    expect(matchScale("my-face", "gujarati")).toBe(1.25);
  });

  it("keeps the scale within limits, and 1 when nothing can be measured", () => {
    fakeCanvas(10);
    expect(matchScale("my-face", "devanagari")).toBe(1.6);
    fakeCanvas(0);
    expect(matchScale("my-face", "gujarati")).toBe(1);
  });
});
