import { render, screen } from "@testing-library/react";
import TryIt from "./TryIt";

// One smoke test: the newest build is loaded by its own file name; the text comes back marked akshara by akshara.
const REPORT = { build: 3, file: "Font-3.ttf", labels: [], filled: [], missing: [] };
const RESULT = {
  build: 3, counts: { book: 1, pieced: 0, filled: 0, missing: 1, other: 0 },
  aksharas: [{ text: "श्री", kind: "book" }, { text: " ", kind: "space" }, { text: "ळ", kind: "missing" }],
};

test("loads the newest build and marks the aksharas", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.endsWith("/coverage") ? RESULT : { job: { running: false }, report: REPORT, coverage: {} }))));
  const { container } = render(<TryIt fontId="f0001" />);
  expect(await screen.findByText("Download Font-3.ttf")).toBeInTheDocument();
  expect(container.querySelector("style")!.textContent).toContain("/files/fonts/f0001/builds/Font-3.ttf");
  expect(await screen.findByText("ळ", { selector: ".ak.missing" })).toBeInTheDocument();
  vi.unstubAllGlobals();
});
