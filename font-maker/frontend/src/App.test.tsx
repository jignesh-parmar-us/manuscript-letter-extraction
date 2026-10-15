import { render, screen } from "@testing-library/react";
import App from "./App";

// One smoke test (Font Maker keeps its screen tests few): the main page shows the library it reads.
test("shows the library and its number of books", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ name: "Font Maker", version: "0.1.0", library: "/lib", books: 2 }))),
  );
  render(<App />);
  expect(await screen.findByText("/lib")).toBeInTheDocument();
  expect(screen.getByText(/2 books/)).toBeInTheDocument();
  vi.unstubAllGlobals();
});
