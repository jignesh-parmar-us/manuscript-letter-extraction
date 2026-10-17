import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, AppInfo, BookSummary, Job } from "../api";
import Books from "./Books";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { books: vi.fn(), datasets: vi.fn(), createBook: vi.fn(), renameBook: vi.fn(), deleteBook: vi.fn(),
    uploadPage: vi.fn(), pickFolder: vi.fn(), chooseLibrary: vi.fn(), chooseUploads: vi.fn(),
    job: vi.fn(), pageMoveSeen: vi.fn() } };
});

const dataset: BookSummary = {
  id: 1, name: "Vachanamrut", kind: "dataset", datasets: [], used_by: [], input_dir: "/pages", writing: "handwritten", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 2, samples: 854, groups: 54, labelled: 27, unsure: 236,
  created_at: null, updated_at: "2026-10-04T09:00:00+00:00", captured_at: null,
};
const reading: BookSummary = { ...dataset, id: 2, name: "Vachanamrut 1933", kind: "book", datasets: [{ id: 1, name: "Vachanamrut" }], input_dir: "", read_pages: 312, pages: 0, samples: 0, groups: 0, labelled: 0, unsure: 0 };
const info: AppInfo = { version: "0.1.0", library: "/lib", mode: "browser", can_pick_folder: false, uploads: "/lib/uploads" };
const made = { ...reading, id: 8, settings: {}, undo: 0, redo: 0, job: null };

describe("Books", () => {
  beforeEach(() => {
    vi.mocked(api.datasets).mockResolvedValue([dataset]);
    vi.mocked(api.books).mockResolvedValue([reading]);
    vi.mocked(api.uploadPage).mockReset();
    window.location.hash = "";
  });

  it("lists only the books, with the dataset each learns from", async () => {
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const books = await screen.findByRole("table", { name: "Books" });
    expect(within(books).getByText("312")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Datasets" })).not.toBeInTheDocument();
    expect(screen.getByText("/lib/uploads")).toBeInTheDocument();                              // where uploads go
    await userEvent.click(within(books).getByRole("button", { name: "Vachanamrut" }));       // learns from
    expect(window.location.hash).toBe("#/books/1");
  });

  it("creates a printed book that learns from a dataset, uploads its images and opens Prepare", async () => {
    vi.mocked(api.datasets).mockResolvedValue([dataset, { ...dataset, id: 3, name: "Printed set", writing: "printed" }]);
    vi.mocked(api.createBook).mockResolvedValue(made);
    vi.mocked(api.uploadPage).mockResolvedValue({ book: made, job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await screen.findByRole("table", { name: "Books" });
    await userEvent.click(screen.getByRole("radio", { name: /Printed/ }));
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "Printed book");
    const from = screen.getByLabelText("Learns from");
    await waitFor(() => expect(from.querySelectorAll("option")).toHaveLength(2));
    expect([...from.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["no dataset yet", "Printed set (0 reviewed letters)"]);
    await userEvent.selectOptions(from, "3");
    const files = [new File(["a"], "p1.png", { type: "image/png" }), new File(["b"], "p2.png", { type: "image/png" })];
    await userEvent.upload(screen.getByLabelText("Page images or a PDF"), files);
    expect(screen.getByText("2 page images")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create book" }));
    expect(api.createBook).toHaveBeenCalledWith("Printed book", "printed", 3);
    await waitFor(() => expect(window.location.hash).toBe("#/books/8/read"));
    expect(vi.mocked(api.uploadPage).mock.calls.map((c) => [c[0], c[1], c[2].name])).toEqual([["book", 8, "p1.png"], ["book", 8, "p2.png"]]);
  });

  it("refuses a PDF with images, and says what happened when an upload fails", async () => {
    vi.mocked(api.createBook).mockResolvedValue(made);
    vi.mocked(api.uploadPage).mockResolvedValueOnce({ book: made, job: null }).mockRejectedValueOnce(new Error("'p2.png' is uploaded already."));
    render(<Books info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "B");
    const picker = screen.getByLabelText("Page images or a PDF");
    await userEvent.upload(picker, [new File(["a"], "book.pdf", { type: "application/pdf" }), new File(["b"], "p1.png", { type: "image/png" })]);
    expect(screen.getByRole("alert")).toHaveTextContent("not both");
    expect(screen.getByRole("button", { name: "Create book" })).toBeDisabled();
    await userEvent.upload(picker, [new File(["a"], "p1.png", { type: "image/png" }), new File(["b"], "p2.png", { type: "image/png" })]);
    await userEvent.click(screen.getByRole("button", { name: "Create book" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/"B" was made.*p2.png was not uploaded \(1 of 2 were\)/);
    expect(window.location.hash).toBe("");
  });

  it("asks before deleting, and says uploaded pages go too", async () => {
    vi.mocked(api.deleteBook).mockResolvedValue(undefined);
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const books = await screen.findByRole("table", { name: "Books" });
    await userEvent.click(within(books).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("Pages uploaded into it are deleted too");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).toHaveBeenCalledWith(2);
  });

  it("renames inline", async () => {
    vi.mocked(api.renameBook).mockResolvedValue({ ...made, name: "Renamed" });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const books = await screen.findByRole("table", { name: "Books" });
    await userEvent.click(within(books).getByRole("button", { name: "Rename" }));
    const field = screen.getByLabelText("New name");
    await userEvent.clear(field);
    await userEvent.type(field, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.renameBook).toHaveBeenCalledWith(2, "Renamed");
  });

  it("changes the uploads folder", async () => {
    vi.mocked(api.chooseUploads).mockResolvedValue({ uploads: "/big/disk", job: null });
    render(<Books info={info} onLibraryChanged={() => {}} />);
    const card = screen.getByText(/Uploaded pages are kept in/);
    await userEvent.click(within(card).getByRole("button", { name: "change…" }));
    expect(screen.getByText(/pages uploaded before are copied there too/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("New uploads folder"), "/big/disk");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.chooseUploads).toHaveBeenCalledWith("/big/disk");
    expect(await screen.findByText("Saved. Uploads go there from now on.")).toBeInTheDocument();
  });

  it("follows the move of the uploaded pages into the new uploads folder (C26)", async () => {
    const job: Job = { id: "m1", book_id: 0, kind: "move_uploads", status: "running", done: 0, total: 2, current: "",
      pages: [], result: null, error: "", seconds: 0 };
    vi.mocked(api.chooseUploads).mockResolvedValue({ uploads: "/big/disk", job });
    vi.mocked(api.job).mockResolvedValue({ ...job, status: "done", done: 2, result: { files: 2, old: "/lib/uploads" } });
    const onLibraryChanged = vi.fn();
    render(<Books info={info} onLibraryChanged={onLibraryChanged} />);
    await userEvent.click(within(screen.getByText(/Uploaded pages are kept in/)).getByRole("button", { name: "change…" }));
    await userEvent.type(screen.getByLabelText("New uploads folder"), "/big/disk");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Moving the uploaded pages: 0 of 2/)).toBeInTheDocument();
    expect(await screen.findByText(/2 uploaded page files were moved there/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(onLibraryChanged).toHaveBeenCalled();
  });

  it("shows once what was moved into the uploads folder at the start (C26)", async () => {
    vi.mocked(api.pageMoveSeen).mockResolvedValue({ ok: true });
    const onLibraryChanged = vi.fn();
    const moved: AppInfo = { ...info, page_move: { at: "", backup: "/lib backups/x/", old_folders: ["/Downloads/scans"],
      moved: [{ id: 1, name: "Printed", kind: "dataset", from: "/Downloads/scans", to: "/lib/uploads/datasets/x", files: 23 }],
      failed: [{ id: 5, name: "Handwritten", problem: "its folder /gone is not there" }] } };
    render(<Books info={moved} onLibraryChanged={onLibraryChanged} />);
    const note = screen.getByRole("status", { name: "Page images moved" });
    expect(note).toHaveTextContent("23 files of 1 row were copied there");
    expect(note).toHaveTextContent("/Downloads/scans");
    expect(note).toHaveTextContent("Handwritten: its folder /gone is not there");
    await userEvent.click(within(note).getByRole("button", { name: "OK" }));
    expect(api.pageMoveSeen).toHaveBeenCalled();
    await waitFor(() => expect(onLibraryChanged).toHaveBeenCalled());
  });
});
