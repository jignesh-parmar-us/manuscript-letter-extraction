import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book } from "../api";
import BookView from "./BookView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { book: vi.fn() } };
});

const book: Book = {
  id: 7, name: "Vachnamrut Printed", input_dir: "/pages", writing: "printed", read_dir: "", read_pdf: "", read_pages: 312, reviewed: 2823, pages: 23, samples: 15169, groups: 531,
  labelled: 82, unsure: 3644, created_at: null, updated_at: null, captured_at: null, settings: {}, undo: 0, redo: 0,
  job: null,
};

describe("BookView", () => {
  beforeEach(() => {
    vi.mocked(api.book).mockResolvedValue(book);
    window.location.hash = "";
  });

  it("puts the book's sections, name and numbers in the one top bar", async () => {
    render(<BookView bookId={7} tab="export" info={null} />);
    const bar = screen.getByRole("banner");
    expect(await screen.findByText("Vachnamrut Printed")).toBeInTheDocument();
    expect(bar).toHaveTextContent("Printed · Training: 23 pages · 2823 reviewed letters · 3644 unsure | Book: 312 pages");
    const menu = screen.getByRole("combobox", { name: "Section" });
    expect(menu).toHaveValue("export");
    const parts = [...menu.querySelectorAll("optgroup")].map((g) => [g.label, [...g.querySelectorAll("option")].map((o) => o.textContent)]);
    expect(parts).toEqual([
      ["Training Data", ["Pages & capture", "Review groups", "Pages", "Export dataset"]],
      ["Read Book", ["Upload & capture", "Book pages"]],
    ]);
    await userEvent.selectOptions(menu, "review");
    expect(window.location.hash).toBe("#/books/7/review");
    await userEvent.click(screen.getByRole("button", { name: "Books" }));
    expect(window.location.hash).toBe("#/");
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/help/new-book.html");
  });
});
