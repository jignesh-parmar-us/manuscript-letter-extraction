import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

// A few smoke tests (Font Maker keeps its screen tests few): the fake backend answers by address.
const BOOK = {
  id: 6, name: "Vachnamrut 1944", writing: "printed", samples: 9455,
  groups: { auto: 171, reviewed: 0, labelled: 541 }, usable: { auto: 160, labelled: 535 },
};
const FONT = {
  id: "f0001", name: "Old font", sources: [6], statuses: ["labelled"], builds: 2, last_build: null,
  created_at: "", updated_at: "",
};

function backend(fonts: object[]) {
  const calls: { method: string; url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ method: init.method ?? "GET", url, body: init.body as string | undefined });
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    if (init.method === "POST") return new Response(JSON.stringify({ ...FONT, id: "f0002" }));
    const answers: Record<string, unknown> = { "/api/app": { library: "/lib", books: 1 }, "/api/sources": [BOOK], "/api/fonts": fonts };
    return new Response(JSON.stringify(answers[url] ?? FONT));
  }));
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

test("New font: the name starts as the book's name and can be changed", async () => {
  const calls = backend([]);
  render(<App />);
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "6" } });
  const name = screen.getByLabelText(/Name/) as HTMLInputElement;
  expect(name.value).toBe("Vachnamrut 1944");
  expect(screen.getByText("(535 groups)")).toBeInTheDocument();
  fireEvent.change(name, { target: { value: "My font" } });
  fireEvent.click(screen.getByRole("button", { name: "Create font" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  expect(JSON.parse(calls.find((c) => c.method === "POST")!.body!)).toEqual({ name: "My font", book_id: 6, statuses: ["labelled"] });
});

test("Delete asks first, and deletes only after OK", async () => {
  const calls = backend([FONT]);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog")).toHaveTextContent('Delete the font "Old font"? Its 2 builds are deleted too.');
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Delete" }).at(-1)!);
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/fonts/f0001")).toBe(true));
});
