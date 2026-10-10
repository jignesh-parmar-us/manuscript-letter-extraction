import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, Book, Job } from "../api";
import ReadBook from "./ReadBook";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pages: vi.fn(), pageProblems: vi.fn(), readPdf: vi.fn(), readFolder: vi.fn(),
    readCapture: vi.fn(), cancelJob: vi.fn(), job: vi.fn(), pickFolder: vi.fn() } };
});

const book = (over: Partial<Book> = {}): Book => ({
  id: 4, name: "B", input_dir: "/train", writing: "printed", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 23, samples: 100, groups: 10, labelled: 5, unsure: 3, created_at: null, updated_at: null, captured_at: null,
  settings: {}, undo: 0, redo: 0, job: null, ...over,
});
const job = (kind: Job["kind"]): Job => ({ id: "j", book_id: 4, kind, status: "running", done: 0, total: 3, current: "",
  pages: [], result: null, error: "", seconds: 0 });

describe("ReadBook", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([]);
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

  it("takes a folder, cuts the remaining pages and lists them", async () => {
    vi.mocked(api.readFolder).mockResolvedValue(book({ read_dir: "/scans" }));
    vi.mocked(api.pageProblems).mockResolvedValue([{ file: "p3.png", problem: "new" }]);
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "p1.png", width: 10, height: 10, status: "OK", message: "", lines: 12, samples: 340, image: "", part: "read", number: 1 },
      { id: 10, file: "p2.png", width: 10, height: 10, status: "OK", message: "", lines: 11, samples: 300, image: "", part: "read", number: 2 },
    ]);
    vi.mocked(api.readCapture).mockResolvedValue(job("capture_read"));
    const onChanged = vi.fn();
    render(<ReadBook book={book({ read_dir: "/scans" })} info={null} onChanged={onChanged} />);
    expect(await screen.findByText("2 of 3 pages cut")).toBeInTheDocument();
    expect(api.pages).toHaveBeenCalledWith(4, "read");
    const input = screen.getByLabelText("Folder of page images");
    await userEvent.clear(input);
    await userEvent.type(input, "/other");
    await userEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(api.readFolder).toHaveBeenCalledWith(4, "/other", false);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Cut the remaining pages (1)" }));
    expect(api.readCapture).toHaveBeenCalledWith(4);
    expect(await screen.findByText(/Cutting the Read Book pages/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use this folder" })).toBeDisabled();   // not while cutting
    const list = screen.getByRole("table", { name: "Read Book pages" });
    await userEvent.click(within(list).getAllByRole("button", { name: "Open" })[1]);
    expect(window.location.hash).toBe("#/books/4/readpages/10");
  });
});
