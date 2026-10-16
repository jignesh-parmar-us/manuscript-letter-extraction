import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, BookSummary, Job, ReadingSetupInfo } from "../api";
import ReadingSetup from "./ReadingSetup";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { readingSetup: vi.fn(), setBookDatasets: vi.fn(), lineSearchTrain: vi.fn(), lineSearchMeasure: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), bookLanguage: vi.fn(), wordLists: vi.fn() } };
});

const ds = (id: number, name: string, over: Partial<BookSummary> = {}): BookSummary => ({
  id, name, kind: "dataset", datasets: [], used_by: [], input_dir: "", writing: "printed", read_dir: "", read_pdf: "",
  read_pages: 0, reviewed: 900, reader_id: null, pages: 23, samples: 1000, groups: 50, labelled: 40, unsure: 3,
  created_at: null, updated_at: null, captured_at: null, ...over });
const book: Book = { ...ds(8, "Vachanamrut 1933"), kind: "book", datasets: [{ id: 1, name: "Set A" }], settings: {}, undo: 0,
  redo: 0, job: null };
const setup = (over: Partial<ReadingSetupInfo> = {}): ReadingSetupInfo => ({
  model: { id: 3, name: "Vachanamrut 1933", folder: "/lib/models/0008-vachanamrut-1933" }, writing: "printed",
  datasets: [ds(1, "Set A")], others: [ds(2, "Hand set", { writing: "handwritten" })],
  reader: { letters: 900, labels: 60, lines: 73, trained_at: "2026-10-16T10:00:00+00:00", seconds: 30, changed: false },
  measure: null, quick_measure: null, ...over });

describe("ReadingSetup", () => {
  beforeEach(() => {
    vi.mocked(api.readingSetup).mockResolvedValue(setup());
    vi.mocked(api.bookLanguage).mockResolvedValue({ enabled: true, labels: { stretches: 0, aksharas: 0 },
      proofread: { lines: 0, aksharas: 0 }, lists: [], aksharas: 0 });
    vi.mocked(api.wordLists).mockResolvedValue([]);
    window.location.hash = "";
  });

  it("shows the datasets used, the word lists and the reading model", async () => {
    render(<ReadingSetup book={book} onChanged={() => {}} />);
    const used = await screen.findByRole("table", { name: "Datasets used" });
    expect(within(used).getByText("Set A")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Word lists" })).toBeInTheDocument();
    expect(screen.getByText("up to date")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrain" })).toBeInTheDocument();
    await userEvent.click(within(used).getByRole("button", { name: "Open" }));
    expect(window.location.hash).toBe("#/books/1");
  });

  it("adds a dataset of another writing, warning about it, and removes one", async () => {
    vi.mocked(api.setBookDatasets)
      .mockResolvedValueOnce(setup({ datasets: [ds(1, "Set A"), ds(2, "Hand set", { writing: "handwritten" })], others: [],
        reader: { letters: 900, labels: 60, lines: 73, trained_at: "2026-10-16T10:00:00+00:00", seconds: 30, changed: true } }))
      .mockResolvedValueOnce(setup({ datasets: [ds(2, "Hand set", { writing: "handwritten" })], others: [ds(1, "Set A")] }));
    const onChanged = vi.fn();
    render(<ReadingSetup book={book} onChanged={onChanged} />);
    const pick = await screen.findByLabelText("Dataset to add");
    expect(within(pick).getByRole("option", { name: /Hand set.*other writing/ })).toBeInTheDocument();
    await userEvent.selectOptions(pick, "2");
    await userEvent.click(screen.getByRole("button", { name: "Add dataset" }));
    expect(api.setBookDatasets).toHaveBeenCalledWith(8, [1, 2]);
    expect(await screen.findByText("the book is printed")).toBeInTheDocument();
    expect(screen.getByText("out of date")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
    const used = screen.getByRole("table", { name: "Datasets used" });
    await userEvent.click(within(used).getAllByRole("button", { name: "Remove from this book" })[0]);
    expect(api.setBookDatasets).toHaveBeenLastCalledWith(8, [2]);
  });

  it("trains when there is no reader yet, and says a dataset is needed", async () => {
    vi.mocked(api.readingSetup).mockResolvedValue(setup({ reader: null }));
    vi.mocked(api.lineSearchTrain).mockResolvedValue({ id: "j", book_id: 8, kind: "line_search_train", status: "running",
      done: 0, total: 0, current: "", pages: [], result: null, error: "", seconds: 0 } as Job);
    render(<ReadingSetup book={book} onChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Train" }));
    await waitFor(() => expect(api.lineSearchTrain).toHaveBeenCalledWith(8));
  });

  it("without datasets, Train and Measure wait", async () => {
    vi.mocked(api.readingSetup).mockResolvedValue(setup({ datasets: [], reader: null }));
    render(<ReadingSetup book={book} onChanged={() => {}} />);
    expect(await screen.findByText(/No dataset yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Train" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Measure" })).toBeDisabled();
  });
});
