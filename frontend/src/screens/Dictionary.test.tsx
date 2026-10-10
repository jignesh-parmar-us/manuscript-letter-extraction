import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, WordListInfo } from "../api";
import Dictionary from "./Dictionary";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { bookLanguage: vi.fn(), wordLists: vi.fn(), importWordList: vi.fn(), useWordList: vi.fn(),
    deleteWordList: vi.fn(), setSettings: vi.fn() } };
});

const book = { id: 6, name: "Printed", settings: { cut_method: "tesseract" }, job: null } as unknown as Book;
const list = (over: Partial<WordListInfo> = {}): WordListInfo => ({
  id: 1, name: "Vachanamrut", file: "0001-vachanamrut.txt", lines: 4200, aksharas: 812000, books: [6], created_at: null,
  ...over,
});

describe("Dictionary", () => {
  beforeEach(() => {
    vi.mocked(api.bookLanguage).mockResolvedValue({ enabled: true, labels: { stretches: 900, aksharas: 13000 },
      proofread: { lines: 12, aksharas: 700 }, lists: [list()], aksharas: 825700 });
    vi.mocked(api.wordLists).mockResolvedValue([list(), list({ id: 2, name: "Sanskrit", books: [] })]);
  });

  it("shows what the model learns from and imports a text file for this book", async () => {
    vi.mocked(api.importWordList).mockResolvedValue(list({ id: 3 }));
    render(<Dictionary book={book} onChanged={() => {}} />);
    const learns = await screen.findByLabelText("Learns from");
    expect(learns).toHaveTextContent("13,000 letters");
    expect(learns).toHaveTextContent("825,700 letters");
    await userEvent.type(screen.getByLabelText("Text file"), "/books/vachanamrut.txt");
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(api.importWordList).toHaveBeenCalledWith("/books/vachanamrut.txt", "", 6);
    await waitFor(() => expect(api.wordLists).toHaveBeenCalledTimes(2));            // reloaded
  });

  it("chooses the lists this book uses and turns the model off", async () => {
    vi.mocked(api.useWordList).mockResolvedValue(list({ id: 2, books: [6] }));
    vi.mocked(api.setSettings).mockResolvedValue(book);
    render(<Dictionary book={book} onChanged={() => {}} />);
    const table = await screen.findByLabelText("Word lists");
    expect(within(table).getByLabelText("Use Vachanamrut for this book")).toBeChecked();
    await userEvent.click(within(table).getByLabelText("Use Sanskrit for this book"));
    expect(api.useWordList).toHaveBeenCalledWith(2, 6, true);
    await userEvent.click(screen.getByLabelText(/Use the language model/));
    expect(api.setSettings).toHaveBeenCalledWith(6, { cut_method: "tesseract", language_model: false });
  });
});
