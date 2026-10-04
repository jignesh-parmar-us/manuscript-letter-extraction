import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, AppInfo, BookSummary } from "../api";
import Books from "./Books";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { books: vi.fn(), createBook: vi.fn(), renameBook: vi.fn(), deleteBook: vi.fn(),
    pickFolder: vi.fn(), chooseLibrary: vi.fn() } };
});

const book: BookSummary = {
  id: 1, name: "Vachanamrut", input_dir: "/pages", writing: "handwritten",
  pages: 2, samples: 854, groups: 54, labelled: 27, unsure: 236,
  created_at: null, updated_at: "2026-10-04T09:00:00+00:00", captured_at: null,
};
const info: AppInfo = { version: "0.1.0", library: "/lib", mode: "browser", can_pick_folder: false };

describe("Books", () => {
  beforeEach(() => {
    vi.mocked(api.books).mockResolvedValue([book]);
    window.location.hash = "";
  });

  it("lists the books with their numbers", async () => {
    render(<Books info={info} onLibraryChanged={() => {}} />);
    expect(await screen.findByText("Vachanamrut")).toBeInTheDocument();
    expect(screen.getByText("854")).toBeInTheDocument();
    expect(screen.getByText("(50%)")).toBeInTheDocument();
  });

  it("creates a book and opens it", async () => {
    vi.mocked(api.createBook).mockResolvedValue({ ...book, id: 7, settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "New book");
    await userEvent.type(screen.getByPlaceholderText("/path/to/the/page/images"), "/pages");
    await userEvent.click(screen.getByRole("button", { name: "Create book" }));
    expect(api.createBook).toHaveBeenCalledWith("New book", "/pages", "handwritten");
    await waitFor(() => expect(window.location.hash).toBe("#/books/7"));
  });

  it("creates a printed book", async () => {
    vi.mocked(api.createBook).mockResolvedValue({ ...book, id: 8, writing: "printed", settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "Printed book");
    await userEvent.type(screen.getByPlaceholderText("/path/to/the/page/images"), "/pages");
    await userEvent.click(screen.getByRole("radio", { name: /Printed/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create book" }));
    expect(api.createBook).toHaveBeenCalledWith("Printed book", "/pages", "printed");
  });

  it("asks before deleting", async () => {
    vi.mocked(api.deleteBook).mockResolvedValue(undefined);
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(api.deleteBook).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("The input pages are not touched");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).toHaveBeenCalledWith(1);
  });

  it("renames inline", async () => {
    vi.mocked(api.renameBook).mockResolvedValue({ ...book, name: "Renamed", settings: {}, undo: 0, redo: 0, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Rename" }));
    const field = screen.getByLabelText("New name");
    await userEvent.clear(field);
    await userEvent.type(field, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.renameBook).toHaveBeenCalledWith(1, "Renamed");
  });

  it("offers the folder dialog only in the app window", async () => {
    const { unmount } = render(<Books info={info} onLibraryChanged={() => {}} />);
    await screen.findByText("Vachanamrut");
    expect(screen.queryByRole("button", { name: "Browse…" })).toBeNull();
    unmount();
    render(<Books info={{ ...info, mode: "window", can_pick_folder: true }} onLibraryChanged={() => {}} />);
    expect((await screen.findAllByRole("button", { name: "Browse…" })).length).toBeGreaterThan(0);
  });
});
