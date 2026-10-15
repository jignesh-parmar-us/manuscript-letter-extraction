// @ts-ignore -- Node's type definitions are not installed; vitest runs in Node
import { readFileSync } from "node:fs";
import { aksharaStartBefore, DEV, splitSpans } from "./letters";

// Font Maker keeps its own copy of the reading app's palette keys: every key of the reading app must be here.
test("the palette copy has every key of the reading app", () => {
  const source: string = readFileSync("../../frontend/src/components/LetterPalette.tsx", "utf8");
  const block = source.slice(source.indexOf("export const DEV"), source.indexOf("};", source.indexOf("export const DEV")));
  const code = block.replace(/\/\/.*$/gm, ""); // the keys only, not the examples in its comments
  const theirs = new Set<string>(code.match(/[ऀ-ॿ]+/g) ?? []);
  const ours = new Set(Object.values(DEV).flat());
  expect(theirs.size).toBeGreaterThanOrEqual(70); // the key lists were found (80 on 2026-10-16)
  expect([...theirs].filter((k) => !ours.has(k))).toEqual([]);
});

test("aksharas are split as the reading app splits them", () => {
  expect(splitSpans("कि क्ति").map(([a, b]) => "कि क्ति".slice(a, b))).toEqual(["कि", "क्ति"]);
  expect(aksharaStartBefore("श्री कि", 7)).toBe(5);       // ⌫ akshara removes कि at once
  expect(aksharaStartBefore("श्री ", 5)).toBe(4);          // after a space: the space
});
