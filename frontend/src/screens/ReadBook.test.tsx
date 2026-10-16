import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, Book, Job, PageEntry } from "../api";
import ReadBook from "./ReadBook";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pages: vi.fn(), pageProblems: vi.fn(), pageList: vi.fn(), readPdf: vi.fn(), readFolder: vi.fn(),
    readCapture: vi.fn(), cancelJob: vi.fn(), job: vi.fn(), pickFolder: vi.fn(), setSettings: vi.fn(), uploadPage: vi.fn() } };
});

const book = (over: Partial<Book> = {}): Book => ({
  id: 4, name: "B", kind: "book", dataset_id: null, dataset_name: "", used_by: [], input_dir: "/train", writing: "printed", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 23, samples: 100, groups: 10, labelled: 5, unsure: 3, created_at: null, updated_at: null, captured_at: null,
  settings: {}, undo: 0, redo: 0, job: null, ...over,
});
const job = (kind: Job["kind"]): Job => ({ id: "j", book_id: 4, kind, status: "running", done: 0, total: 3, current: "",
  pages: [], result: null, error: "", seconds: 0 });

describe("ReadBook", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([]);
    vi.mocked(api.pageList).mockResolvedValue({ part: "read", folder: "", owned: false, pages: [] });
    vi.mocked(api.pageProblems).mockResolvedValue([]);
    window.location.hash = "";
  });

  it("takes a PDF, asking before it replaces Read Book pages", async () => {
    vi.mocked(api.readPdf)
      .mockRejectedValueOnce(new ApiError(409, "The book already has 3 Read Book pages.", "needs_confirmation"))
      .mockResolvedValueOnce(job("import_pdf"));
    render(<ReadBook book={book()} info={null} onChanged={() => {}} />);
    expect(screen.getByText(/none yet/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("PDF file"), "/books/vachnamrut.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Use this PDF" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(api.readPdf).toHaveBeenLastCalledWith(4, "/books/vachnamrut.pdf", true));
    expect(await screen.findByText(/Turning the PDF into page images/)).toBeInTheDocument();
  });

  it("uploads a PDF and follows the job that turns it into page images (C21)", async () => {
    vi.mocked(api.uploadPage).mockResolvedValue({ book: null, job: job("import_pdf") });
    render(<ReadBook book={book()} info={null} onChanged={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Upload page images or a PDF"),
      new File(["%PDF"], "book.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(api.uploadPage).toHaveBeenCalledWith("book", 4, expect.any(File));
    expect(await screen.findByText(/Turning the PDF into page images/)).toBeInTheDocument();
  });

  it("adds uploaded pages to a book read from a PDF (C22)", async () => {
    vi.mocked(api.uploadPage).mockResolvedValue({ book: book({ read_pdf: "book.pdf" }), job: null });
    render(<ReadBook book={book({ read_pdf: "book.pdf" })} info={null} onChanged={() => {}} />);
    await userEvent.upload(screen.getByLabelText("Upload page images or a PDF"), new File(["x"], "extra.png", { type: "image/png" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(api.uploadPage).toHaveBeenCalledWith("book", 4, expect.any(File));
  });

  it("takes a folder, prepares the remaining pages for reading and lists them", async () => {
    vi.mocked(api.readFolder).mockResolvedValue(book({ read_dir: "/scans" }));
    vi.mocked(api.pageProblems).mockResolvedValue([{ file: "p3.png", problem: "new" }]);
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "p1.png", width: 10, height: 10, status: "OK", message: "", lines: 12, samples: 340, image: "", part: "read", number: 1 },
      { id: 10, file: "p2.png", width: 10, height: 10, status: "OK", message: "", lines: 11, samples: 300, image: "", part: "read", number: 2 },
    ]);
    const entry = (id: number | null, file: string, over: Partial<PageEntry> = {}): PageEntry => ({ id, file, number: id ? id - 8 : null,
      excluded: false, prepared: id !== null, status: id ? "OK" : "new", message: "", lines: 12, samples: 340, checked: 0,
      corrections: 0, reviewed: 0, missing: false, thumb: "", ...over });
    vi.mocked(api.pageList).mockResolvedValue({ part: "read", folder: "/scans", owned: false,
      pages: [entry(9, "p1.png"), entry(10, "p2.png"), entry(null, "p3.png")] });
    vi.mocked(api.readCapture).mockResolvedValue(job("capture_read"));
    const onChanged = vi.fn();
    render(<ReadBook book={book({ read_dir: "/scans" })} info={null} onChanged={onChanged} />);
    expect(await screen.findByText("2 of 3 pages prepared")).toBeInTheDocument();
    expect(api.pages).toHaveBeenCalledWith(4, "read");
    const input = screen.getByLabelText("Folder of page images");
    await userEvent.clear(input);
    await userEvent.type(input, "/other");
    await userEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(api.readFolder).toHaveBeenCalledWith(4, "/other", false);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Prepare the remaining pages (1)" }));
    expect(api.readCapture).toHaveBeenCalledWith(4);
    expect(await screen.findByText(/Preparing the book pages for reading/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use this folder" })).toBeDisabled();   // not while cutting
    const list = screen.getByRole("table", { name: "Pages" });                       // the page manager (C22)
    expect(within(list).getAllByText("Prepared")).toHaveLength(2);                  // C19: not "OK", not "cut"
    expect(within(list).getByText("Not prepared yet")).toBeInTheDocument();
    expect(within(list).getAllByRole("button", { name: "Prepare again" })).toHaveLength(2);
    await userEvent.click(within(list).getAllByRole("button", { name: "Open" })[1]);
    expect(window.location.hash).toBe("#/books/4/readpages/10");
  });

  it("turns on the hidden Cut letters view, keeping the other settings", async () => {
    const onChanged = vi.fn();
    vi.mocked(api.setSettings).mockResolvedValue(book());
    render(<ReadBook book={book({ settings: { group_distance: 0.55 } })} info={null} onChanged={onChanged} />);
    const show = screen.getByRole("checkbox", { name: /Show Cut letters/ });
    expect(show).not.toBeChecked();                                               // C19: off by default
    await userEvent.click(show);                                                  // C20: a book's setting
    expect(api.setSettings).toHaveBeenCalledWith(4, { group_distance: 0.55, show_cut_letters: true });
    expect(onChanged).toHaveBeenCalled();
  });
});
