import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, Job } from "../api";
import Export from "./Export";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { exportBook: vi.fn(), job: vi.fn(), openFolder: vi.fn(), pickFolder: vi.fn() } };
});

const book = { id: 1, labelled: 2, groups: 54, settings: { dataset_image: "original" } } as unknown as Book;
const job = (over: Partial<Job>): Job => ({
  id: "e1", book_id: 1, kind: "export", status: "running", done: 0, total: 0, current: "", pages: [], result: null,
  error: "", seconds: 0, ...over,
});

describe("Export", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("exports with the chosen images, shows the result and opens the folder", async () => {
    vi.mocked(api.exportBook).mockResolvedValue(job({}));
    vi.mocked(api.job).mockResolvedValue(job({ status: "done", result: { folder: "/lib/books/1/exports/x", classes: 2,
      labelled_samples: 30, few_samples: 1, unsure: 10, pages: 2, lines: 22, uploaded: 0, kept_in_devanagari: [] } }));
    vi.mocked(api.openFolder).mockResolvedValue({ opened: "/lib/books/1/exports/x" });
    render(<Export book={book} info={null} />);
    await userEvent.click(screen.getByLabelText(/64 × 64/));
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(api.exportBook).toHaveBeenCalledWith(1, null, "fixed64");
    await act(() => vi.advanceTimersByTimeAsync(1100));
    expect(await screen.findByText("/lib/books/1/exports/x")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the folder" }));
    expect(api.openFolder).toHaveBeenCalledWith("/lib/books/1/exports/x");
  });

  it("exports into another folder", async () => {
    vi.mocked(api.exportBook).mockResolvedValue(job({ status: "failed", error: "The export folder must be new or empty" }));
    render(<Export book={book} info={null} />);
    await userEvent.click(screen.getByLabelText(/In another folder/));
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Export folder"), "/data/out");
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(api.exportBook).toHaveBeenCalledWith(1, "/data/out", "original");
    expect(await screen.findByText("The export folder must be new or empty")).toBeInTheDocument();
  });
});
