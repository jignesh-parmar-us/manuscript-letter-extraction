import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TryIt from "./TryIt";

// Smoke tests: the newest build is used by its own file name; the check line lists what is not the book's
// own; a palette key types at the cursor and ⌫ akshara removes a whole akshara.
const REPORT = { build: 3, file: "Font-3.ttf", family: "Font", labels: ["क", "कि", "श्री"], filled: [], missing: ["ळ"] };
const RESULT = {
  build: 3, counts: { book: 1, pieced: 0, filled: 0, missing: 1, other: 0 },
  aksharas: [{ text: "श्री", kind: "book", start: 0 }, { text: " ", kind: "space", start: 4 },
             { text: "ळ", kind: "missing", start: 5, detail: [{ char: "ळ", kind: "missing" }] }],
};

function backend() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/coverage")) return new Response(JSON.stringify(RESULT));
    if (url.endsWith("/texts")) return new Response(JSON.stringify([]));
    return new Response(JSON.stringify({ job: { running: false }, report: REPORT, coverage: {} }));
  }));
}

afterEach(() => vi.unstubAllGlobals());

test("the newest build is used and the check line names what is not the book's own", async () => {
  backend();
  const { container } = render(<TryIt fontId="f0001" />);
  expect(await screen.findByText("Download the font (Font-3.ttf)")).toBeInTheDocument();
  expect(container.querySelector("style")!.textContent).toContain("/files/fonts/f0001/builds/Font-3.ttf");
  expect(await screen.findByText(/2 aksharas: 1 the book's own/)).toBeInTheDocument();
  expect(screen.getByText("(missing ळ)")).toBeInTheDocument();
});

test("a key types at the cursor, ⌫ akshara removes the whole akshara", async () => {
  backend();
  render(<TryIt fontId="f0001" />);
  const box = (await screen.findByLabelText("Text to try")) as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: "श्री " } });
  box.setSelectionRange(5, 5);
  fireEvent.click(screen.getByRole("button", { name: "क" }));
  fireEvent.click(screen.getByRole("button", { name: "ि" }));
  await waitFor(() => expect(box.value).toBe("श्री कि"));
  box.setSelectionRange(7, 7);
  fireEvent.click(screen.getByRole("button", { name: "Remove the akshara before the cursor" }));
  await waitFor(() => expect(box.value).toBe("श्री "));
});
