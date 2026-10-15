import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Glyphs from "./Glyphs";

// One smoke test: the grid shows the glyphs; a click opens one; "Leave out" sends only that group's choice.
const GLYPH = {
  group: 7, book: 6, code: "g0007", kind: "letter", status: "labelled", label_dev: "कि", label_guj: "કિ",
  method: "average", agree: 0.9, used: [1, 2, 3], count: 12, image: "6-g0007-abc.png", left_out: false, lost: false,
};
const STATE = { job: { running: false, done: 0, total: 0, error: null }, glyphs: [GLYPH], cut_errors: [], lost: [] };

test("pick a glyph and leave it out", async () => {
  const calls: { method: string; url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ method: init.method ?? "GET", url, body: init.body as string | undefined });
    if (url.endsWith("/copies")) return new Response(JSON.stringify([{ id: 1, book: 6, image: "letters/a.png" }]));
    if (init.method === "PUT") return new Response(JSON.stringify({ glyph: { ...GLYPH, left_out: true }, lost: [] }));
    return new Response(JSON.stringify(STATE));
  }));
  render(<Glyphs fontId="f0001" />);
  fireEvent.click(await screen.findByTitle("कि કિ: average of 3"));
  expect(await screen.findByLabelText("Use copy 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Leave out of the font" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Use in the font again" })).toBeInTheDocument());
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.url).toBe("/api/fonts/f0001/glyphs/7/choice");
  expect(JSON.parse(put.body!)).toEqual({ choice: "left_out" });
  vi.unstubAllGlobals();
});
