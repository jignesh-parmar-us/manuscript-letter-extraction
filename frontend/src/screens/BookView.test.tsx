import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book } from "../api";
import BookView from "./BookView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { book: vi.fn(), pages: vi.fn(), pageProblems: vi.fn(), pageList: vi.fn() } };
});

const book: Book = {
  id: 7, name: "Vachnamrut Printed", kind: "dataset", datasets: [], used_by: [], input_dir: "/pages", writing: "printed", read_dir: "", read_pdf: "", read_pages: 312, reviewed: 2823, reader_id: null, pages: 23, samples: 15169, groups: 531,
  labelled: 82, unsure: 3644, created_at: null, updated_at: null, captured_at: null, settings: {}, undo: 0, redo: 0,
  job: null,
};

describe("BookView", () => {
  beforeEach(() => {
    vi.mocked(api.book).mockResolvedValue(book);
    vi.mocked(api.pageList).mockResolvedValue({ part: "read", folder: "", owned: false, pages: [] });
    window.location.hash = "";
  });

  it("puts a dataset's sections, name and numbers in the one top bar", async () => {
    vi.mocked(api.book).mockResolvedValue({ ...book, read_pages: 0, used_by: [{ id: 8, name: "Vachnamrut 1933" }] });
    render(<BookView bookId={7} tab="export" info={null} />);
    const bar = screen.getByRole("banner");
    expect(await screen.findByText("Vachnamrut Printed")).toBeInTheDocument();
    expect(bar).toHaveTextContent("Dataset · Printed · 23 pages · 2823 reviewed letters · 3644 unsure · used by Vachnamrut 1933");
    const menu = screen.getByRole("combobox", { name: "Section" });
    expect(menu).toHaveValue("export");
    const parts = [...menu.querySelectorAll("optgroup")].map((g) => [g.label, [...g.querySelectorAll("option")].map((o) => o.textContent)]);
    expect(parts).toEqual([["Dataset", ["Pages & capture", "Review groups", "Pages", "Letter checker", "Export dataset"]]]);
    await userEvent.selectOptions(menu, "review");
    expect(window.location.hash).toBe("#/books/7/review");
    await userEvent.click(screen.getByRole("button", { name: "Books" }));
    expect(window.location.hash).toBe("#/");
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute("href", "/help/new-book.html");
  });

  it("a book has the Read Book sections and links its dataset; another section opens its first", async () => {
    vi.mocked(api.book).mockResolvedValue({ ...book, id: 8, name: "Vachnamrut 1933", kind: "book", datasets: [{ id: 7, name: "Vachnamrut Printed" }], pages: 0, reviewed: 0, unsure: 0 });
    vi.mocked(api.pages).mockResolvedValue([]);
    vi.mocked(api.pageList).mockResolvedValue({ part: "read", folder: "", owned: false, pages: [] });
    vi.mocked(api.pageProblems).mockResolvedValue([]);
    const { rerender } = render(<BookView bookId={8} tab="capture" info={null} />);
    await waitFor(() => expect(window.location.hash).toBe("#/books/8/read"));  // capture is a dataset's
    rerender(<BookView bookId={8} tab="read" info={null} />);                   // as the app does on the new address
    await screen.findByText("Vachnamrut 1933");
    const bar = screen.getByRole("banner");
    expect(bar).toHaveTextContent("Book · Printed · 312 pages · learns from Vachnamrut Printed");
    const menu = screen.getByRole("combobox", { name: "Section" });
    expect([...menu.querySelectorAll("option")].map((o) => o.textContent))
      .toEqual(["Prepare", "Book pages", "Text", "Reading setup", "Line truth"]);     // C23: no Dictionary tab
    await userEvent.click(screen.getByRole("button", { name: "Vachnamrut Printed" }));
    expect(window.location.hash).toBe("#/books/7");
  });

  it("the old Dictionary address of a book opens Reading setup", async () => {
    vi.mocked(api.book).mockResolvedValue({ ...book, id: 8, kind: "book" });
    render(<BookView bookId={8} tab="dictionary" info={null} />);
    await waitFor(() => expect(window.location.hash).toBe("#/books/8/setup"));
  });
});
