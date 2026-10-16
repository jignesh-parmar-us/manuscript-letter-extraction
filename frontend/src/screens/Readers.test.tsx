import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, ReaderInfo } from "../api";
import Readers from "./Readers";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { readers: vi.fn(), datasets: vi.fn(), train: vi.fn(), reader: vi.fn(), useReader: vi.fn(),
    deleteReader: vi.fn(), job: vi.fn(), cancelJob: vi.fn() } };
});

const book = { id: 6, name: "Printed", writing: "printed", reader_id: 2, job: null } as unknown as Book;
const reader = (id: number, over: Partial<ReaderInfo> = {}): ReaderInfo => ({
  id, name: `Reader ${id}`, kind: "features-linear", created_at: null, accuracy: 0.964, accuracy_20: 0.972, labels: 93,
  trained_on: { books: [6], book_names: ["Printed"], letters: 3780, test_pages: 3, test_letters: 535, min_samples: 5,
    left_out: [["घ", 2], ["ङ", 1]] },
  ...over,
});
const job = { id: "j", book_id: 6, kind: "train" as const, status: "running" as const, done: 2, total: 6, current: "training",
  pages: [], result: null, error: "", seconds: 3 };

describe("Letter checker (Readers)", () => {
  beforeEach(() => {
    vi.mocked(api.readers).mockResolvedValue([reader(2), reader(1, { accuracy: 0.9 })]);
    vi.mocked(api.datasets).mockResolvedValue([
      { id: 6, name: "Printed", writing: "printed", reviewed: 4091 } as never,
      { id: 3, name: "Older print", writing: "printed", reviewed: 500 } as never,
    ]);
  });

  it("trains with the chosen books and the least letters a label needs", async () => {
    vi.mocked(api.train).mockResolvedValue(job);
    render(<Readers book={book} onChanged={() => {}} />);
    expect(screen.getByRole("heading", { name: "Letter checker" })).toBeInTheDocument();     // C19: says what it does
    expect(screen.getByText(/probably in the wrong group/)).toHaveTextContent(/It does not read books/);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Older print/ }));
    const least = screen.getByLabelText("Least letters a label needs");
    fireEvent.change(least, { target: { value: "1" } });
    expect(screen.getByText(/cannot be measured/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Train" }));
    expect(api.train).toHaveBeenCalledWith(6, { books: [6, 3], min_samples: 1, include_unreviewed: false, include_words: false });
    expect(await screen.findByText(/Training a letter checker/)).toBeInTheDocument();
  });

  it("lists readers, marks the active one, shows a report, and switches readers", async () => {
    vi.mocked(api.reader).mockResolvedValue(reader(2, {
      per_label: [{ label: "या", letters: 40, tested: 9, accuracy: 0.78 }, { label: "घ", letters: 3, tested: 0, accuracy: null }],
      confusions: [["था", "या", 2]], check: 23, seconds: 77,
    }));
    vi.mocked(api.useReader).mockResolvedValue({ ...job, kind: "use_reader" });
    render(<Readers book={book} onChanged={() => {}} />);
    const table = await screen.findByRole("table", { name: "Letter checkers" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Reader 2 active");
    expect(rows[1]).toHaveTextContent("96.4%");
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Report" }));
    const report = await screen.findByLabelText("Report");
    expect(report).toHaveTextContent("23 letters to check");
    expect(report).toHaveTextContent("થા → યા (2)");
    expect(within(report).getByText("not measured")).toBeInTheDocument();
    expect(report).toHaveTextContent("ઘ (2) · ઙ (1)");
    await userEvent.click(within(rows[2]).getByRole("button", { name: "Use for this book" }));
    expect(api.useReader).toHaveBeenCalledWith(6, 1);
    await waitFor(() => expect(screen.getByText(/Checking the letters with the letter checker/)).toBeInTheDocument());
  });
});
