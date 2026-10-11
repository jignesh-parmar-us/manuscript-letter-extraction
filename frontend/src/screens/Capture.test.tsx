import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, Book, Job } from "../api";
import Capture from "./Capture";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pages: vi.fn(), pageProblems: vi.fn(), capture: vi.fn(), addPages: vi.fn(),
    recutPage: vi.fn(), job: vi.fn(), cancelJob: vi.fn(), setSettings: vi.fn(), setWriting: vi.fn(),
    setInputFolder: vi.fn(), pickFolder: vi.fn() } };
});

const book: Book = {
  id: 1, name: "B", input_dir: "/pages", writing: "handwritten", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 0, samples: 0, groups: 0, labelled: 0, unsure: 0,
  created_at: null, updated_at: null, captured_at: null, settings: { group_distance: 0.55 }, undo: 0, redo: 0, job: null,
};
const job = (over: Partial<Job>): Job => ({
  id: "j1", book_id: 1, kind: "capture", status: "running", done: 0, total: 2, current: "", pages: [], result: null,
  error: "", seconds: 0, ...over,
});

describe("Capture", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.pages).mockResolvedValue([]);
    vi.mocked(api.pageProblems).mockResolvedValue([{ file: "p3.png", problem: "new" }]);
  });
  afterEach(() => vi.useRealTimers());

  it("starts a capture and follows its progress to the end", async () => {
    const onChanged = vi.fn();
    vi.mocked(api.capture).mockResolvedValue(job({}));
    vi.mocked(api.job)
      .mockResolvedValueOnce(job({ done: 1, current: "p1.png" }))
      .mockResolvedValueOnce(job({ done: 2, status: "done", result: { pages: 2, lines: 22, samples: 854, groups: 54, unsure: 236 } }));
    render(<Capture book={book} info={null} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Capture letters" }));
    expect(await screen.findByText(/0 of 2 pages/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1100));
    expect(await screen.findByText(/1 of 2 pages/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1100));
    expect(await screen.findByText(/854 letters, 54 groups, 236 unsure/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("a book without page images chooses its folder here before capturing", async () => {
    const onChanged = vi.fn();
    vi.mocked(api.pageProblems).mockResolvedValue([]);
    vi.mocked(api.setInputFolder).mockResolvedValue({ ...book });
    render(<Capture book={{ ...book, input_dir: "" }} info={null} onChanged={onChanged} />);
    expect(screen.getByRole("button", { name: "Capture letters" })).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText("/path/to/the/page/images"), "/new/pages");
    await userEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(api.setInputFolder).toHaveBeenCalledWith(1, "/new/pages");
    expect(onChanged).toHaveBeenCalled();
  });

  it("offers the folder dialog only in the app window", async () => {
    vi.mocked(api.pickFolder).mockResolvedValue({ path: "/picked" });
    const empty = { ...book, input_dir: "" };
    const { unmount } = render(<Capture book={empty} info={null} onChanged={() => {}} />);
    expect(screen.queryByRole("button", { name: "Browse…" })).toBeNull();
    unmount();
    const info = { version: "0.1.0", library: "/lib", mode: "window" as const, can_pick_folder: true };
    render(<Capture book={empty} info={info} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Browse…" }));
    expect(screen.getByPlaceholderText("/path/to/the/page/images")).toHaveValue("/picked");
  });

  it("changes the folder of the page images", async () => {
    vi.mocked(api.setInputFolder).mockResolvedValue({ ...book });
    render(<Capture book={book} info={null} onChanged={() => {}} />);
    expect(screen.getByText("/pages")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change…" }));
    const input = screen.getByPlaceholderText("/path/to/the/page/images");
    await userEvent.clear(input);
    await userEvent.type(input, "/moved");
    await userEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(api.setInputFolder).toHaveBeenCalledWith(1, "/moved");
  });

  it("asks before discarding manual work, then captures with force", async () => {
    vi.mocked(api.capture)
      .mockRejectedValueOnce(new ApiError(409, "The book has labels.", "needs_confirmation"))
      .mockResolvedValueOnce(job({}));
    vi.mocked(api.job).mockResolvedValue(job({ status: "done", done: 2, result: { pages: 2, lines: 1, samples: 1 } }));
    render(<Capture book={{ ...book, captured_at: "2026-10-04T09:00:00+00:00" }} info={null} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Capture again" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("The book has labels. Capture anyway?");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(api.capture).toHaveBeenLastCalledWith(1, true);
  });

  it("changes how the book is written", async () => {
    const onChanged = vi.fn();
    vi.mocked(api.setWriting).mockResolvedValue({ ...book, writing: "printed" });
    render(<Capture book={book} info={null} onChanged={onChanged} />);
    expect(screen.getByRole("radio", { name: /Handwritten/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /Printed/ }));
    expect(api.setWriting).toHaveBeenCalledWith(1, "printed");
    expect(onChanged).toHaveBeenCalled();
  });

  it("chooses how a printed book is cut", async () => {
    const onChanged = vi.fn();
    vi.mocked(api.setSettings).mockResolvedValue({ ...book, writing: "printed" });
    const { unmount } = render(<Capture book={book} info={null} onChanged={onChanged} />);
    expect(screen.queryByRole("radio", { name: /By Tesseract's reading/ })).toBeNull();    // handwritten
    unmount();
    render(<Capture book={{ ...book, writing: "printed" }} info={null} onChanged={onChanged} />);
    expect(screen.getByRole("radio", { name: /By the shapes of the ink/ })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: /By Tesseract's reading/ }));
    expect(api.setSettings).toHaveBeenCalledWith(1, { group_distance: 0.55, cut_method: "tesseract" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows new pages and adds them", async () => {
    vi.mocked(api.addPages).mockResolvedValue(job({ kind: "add_pages", total: 1 }));
    vi.mocked(api.job).mockResolvedValue(job({ kind: "add_pages", status: "done", total: 1, done: 1, result: { pages: 1, lines: 3, samples: 27 } }));
    render(<Capture book={book} info={null} onChanged={() => {}} />);
    const add = await screen.findByRole("button", { name: "Add new pages (1)" });
    await userEvent.click(add);
    expect(api.addPages).toHaveBeenCalledWith(1);
  });

  it("cancels a running job", async () => {
    vi.mocked(api.capture).mockResolvedValue(job({}));
    vi.mocked(api.job).mockResolvedValue(job({}));
    vi.mocked(api.cancelJob).mockResolvedValue(job({ status: "cancelled" }));
    render(<Capture book={book} info={null} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Capture letters" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText(/cancelled, nothing was changed/)).toBeInTheDocument();
  });
});
