import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, Book, Job } from "../api";
import Capture from "./Capture";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pages: vi.fn(), pageProblems: vi.fn(), capture: vi.fn(), addPages: vi.fn(),
    recutPage: vi.fn(), job: vi.fn(), cancelJob: vi.fn(), setSettings: vi.fn() } };
});

const book: Book = {
  id: 1, name: "B", input_dir: "/pages", pages: 0, samples: 0, groups: 0, labelled: 0, unsure: 0,
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
