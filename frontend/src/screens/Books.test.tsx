import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, AppInfo, BookSummary } from "../api";
import Books from "./Books";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { books: vi.fn(), datasets: vi.fn(), createBook: vi.fn(), createDataset: vi.fn(), renameBook: vi.fn(), deleteBook: vi.fn(),
    pickFolder: vi.fn(), chooseLibrary: vi.fn() } };
});

const book: BookSummary = {
  id: 1, name: "Vachanamrut", kind: "dataset", dataset_id: null, dataset_name: "", used_by: [], input_dir: "/pages", writing: "handwritten", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 2, samples: 854, groups: 54, labelled: 27, unsure: 236,
  created_at: null, updated_at: "2026-10-04T09:00:00+00:00", captured_at: null,
};
const reading: BookSummary = { ...book, id: 2, name: "Vachanamrut 1933", kind: "book", dataset_id: 1,
  dataset_name: "Vachanamrut", input_dir: "", read_pages: 312, pages: 0, samples: 0, groups: 0, labelled: 0, unsure: 0 };
const info: AppInfo = { version: "0.1.0", library: "/lib", mode: "browser", can_pick_folder: false };

describe("Books", () => {
  beforeEach(() => {
    vi.mocked(api.datasets).mockResolvedValue([book]);
    vi.mocked(api.books).mockResolvedValue([reading]);
    window.location.hash = "";
  });

  it("lists the books and the datasets with their numbers", async () => {
    vi.mocked(api.datasets).mockResolvedValue([{ ...book, used_by: [{ id: 2, name: "Vachanamrut 1933" }] }]);
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const datasets = await screen.findByRole("table", { name: "Datasets" });
    expect(within(datasets).getByText("854")).toBeInTheDocument();
    expect(within(datasets).getByText("(50%)")).toBeInTheDocument();
    expect(within(datasets).getByText("Vachanamrut 1933")).toBeInTheDocument();               // used by
    const books = await screen.findByRole("table", { name: "Books" });
    expect(within(books).getByText("312")).toBeInTheDocument();
    await userEvent.click(within(books).getByRole("button", { name: "Vachanamrut" }));       // learns from
    expect(window.location.hash).toBe("#/books/1");
  });

  it("creates a dataset and opens it", async () => {
    vi.mocked(api.createDataset).mockResolvedValue({ ...book, id: 7, settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "New set");
    expect(screen.queryByPlaceholderText("/path/to/the/page/images")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    expect(api.createDataset).toHaveBeenCalledWith("New set", "handwritten");
    await waitFor(() => expect(window.location.hash).toBe("#/books/7"));
  });

  it("creates a printed book that learns from a dataset", async () => {
    vi.mocked(api.datasets).mockResolvedValue([book, { ...book, id: 3, name: "Printed set", writing: "printed" }]);
    vi.mocked(api.createBook).mockResolvedValue({ ...reading, id: 8, settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await screen.findByRole("table", { name: "Datasets" });
    await userEvent.click(screen.getByRole("radio", { name: /^Book/ }));
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "Printed book");
    await userEvent.click(screen.getByRole("radio", { name: /Printed/ }));
    const from = screen.getByLabelText("Learns from");
    expect([...from.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["no dataset yet", "Printed set (0 reviewed letters)"]);
    await userEvent.selectOptions(from, "3");
    await userEvent.click(screen.getByRole("button", { name: "Create book" }));
    expect(api.createBook).toHaveBeenCalledWith("Printed book", "printed", 3);
    await waitFor(() => expect(window.location.hash).toBe("#/books/8"));
  });

  it("asks before deleting, and says which books learn from a dataset", async () => {
    vi.mocked(api.datasets).mockResolvedValue([{ ...book, used_by: [{ id: 2, name: "Vachanamrut 1933" }] }]);
    vi.mocked(api.deleteBook).mockResolvedValue(undefined);
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const datasets = await screen.findByRole("table", { name: "Datasets" });
    await userEvent.click(within(datasets).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("The input pages are not touched");
    expect(screen.getByRole("dialog")).toHaveTextContent('"Vachanamrut 1933" learn from it');
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).toHaveBeenCalledWith(1);
  });

  it("renames inline", async () => {
    vi.mocked(api.renameBook).mockResolvedValue({ ...book, name: "Renamed", settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const datasets = await screen.findByRole("table", { name: "Datasets" });
    await userEvent.click(within(datasets).getByRole("button", { name: "Rename" }));
    const field = screen.getByLabelText("New name");
    await userEvent.clear(field);
    await userEvent.type(field, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.renameBook).toHaveBeenCalledWith(1, "Renamed");
  });
});
