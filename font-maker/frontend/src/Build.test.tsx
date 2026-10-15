import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Build from "./Build";

// One smoke test: the missing characters can be filled; Generate waits for the next phase; Build starts a build.
const COVERAGE = {
  base: 47, aksharas: 485, generated: 116, estimated: 116, left_out: [], duplicates: [], filled: [],
  missing: ["ग", "ं"], labels: ["क"],
};
const STATE = { job: { running: false, done: 0, total: 0, error: null, phase: "" }, report: null, coverage: COVERAGE, builds: 0, mark_filled: true };

test("fill a missing character and build", async () => {
  const calls: { method: string; url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ method: init.method ?? "GET", url, body: init.body as string | undefined });
    if (init.method === "PUT") return new Response(JSON.stringify({ ...STATE, coverage: { ...COVERAGE, missing: ["ं"], filled: ["ग"] } }));
    return new Response(JSON.stringify(STATE));
  }));
  render(<Build fontId="f0001" />);
  expect(await screen.findByText(/116 made by the system, 116 with an estimated place/)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Generate" })[0]).toBeDisabled();
  fireEvent.click(screen.getAllByRole("button", { name: "Fill" })[0]);
  expect(await screen.findByRole("button", { name: "Remove fill" })).toBeInTheDocument();
  expect(JSON.parse(calls.find((c) => c.method === "PUT")!.body!)).toEqual({ chars: ["ग"], filled: true });
  fireEvent.click(screen.getByRole("button", { name: "Build font" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/fonts/f0001/build")).toBe(true));
  vi.unstubAllGlobals();
});
