import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, WholeLines } from "../api";
import TextView from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookWholeLines: vi.fn(), wholeLines: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), proofreadStats: vi.fn() } };
});

const book = { id: 4, job: null } as unknown as Book;
const ak = (dev: string, guj: string, over = {}) => ({ text_dev: dev, text_guj: guj, conf: 96, space: false, uncertain: false, ...over });
const text: WholeLines = {
  page_id: 9, uncertain: 1, read_at: null,
  lines: [{ line_id: 1, number: 1, box: [10, 10, 300, 40], text_dev: "नारायव भग", text_guj: "નારાયવ ભગ",
    aksharas: [ak("ना", "ના"), ak("रा", "રા"), ak("य", "ય"), ak("व", "વ", { conf: 60, uncertain: true, lm_dev: "ण", lm_guj: "ણ" }),
      ak("भ", "ભ", { space: true }), ak("ग", "ગ")] }],
};

describe("Whole lines", () => {
  beforeEach(() => {
    localStorage.removeItem("text-mode");
    localStorage.removeItem("whole-lines-lm");
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "page-0001.jpg", width: 400, height: 200, status: "OK", message: "", lines: 1, samples: 6, image: "/p/9", part: "read", number: 1 },
      { id: 10, file: "page-0002.jpg", width: 400, height: 200, status: "OK", message: "", lines: 1, samples: 6, image: "/p/10", part: "read", number: 2 },
    ]);
    vi.mocked(api.bookWholeLines).mockResolvedValue([{ page_id: 9, lines: 1 }]);
    vi.mocked(api.wholeLines).mockResolvedValue(text);
  });

  it("opens on whole lines and shows Tesseract's reading with the language model's corrections", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    expect(screen.getByRole("button", { name: "Whole lines (Tesseract)" })).toHaveClass("active");
    const pane = await screen.findByLabelText("Text");
    await waitFor(() => expect(within(pane).getByText("ણ")).toHaveClass("lm"));       // corrected, underlined
    expect(screen.getByText(/1 uncertain aksharas \(highlighted\) · 1 changed by the language model/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Page .txt" }).getAttribute("href")).toMatch(/readers=lines_lm&page_id=9/);
    await userEvent.click(screen.getByLabelText("With the language model"));
    expect(within(pane).getByText("વ")).toHaveClass("uncertain");                    // Tesseract alone
    expect(screen.getByRole("link", { name: "Page .txt" }).getAttribute("href")).toMatch(/readers=lines&page_id=9/);
    await userEvent.click(within(pane).getByText("વ"));
    expect(screen.getByText(/Tesseract: વ \(60\) · the language model: ણ/)).toBeInTheDocument();
    await userEvent.click(within(pane).getByText("ભ"));
    expect(screen.getByLabelText("Page").querySelector(".text-box.selected")).not.toBeNull();   // the line on the page
  });

  it("reads a page whole and switches to the cut-letter view", async () => {
    vi.mocked(api.convert).mockResolvedValue({ id: "j", book_id: 4, kind: "convert", status: "running", done: 0, total: 1,
      current: "", pages: [], result: null, error: "", seconds: 0 });
    vi.mocked(api.bookTexts).mockResolvedValue([]);
    vi.mocked(api.proofreadStats).mockResolvedValue({ lines: 0, chars: 0, cer: null, cer_tesseract: null });
    render(<TextView book={book} pageId={10} onChanged={() => {}} />);
    expect(await screen.findByText(/not read yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Read this page" }));
    expect(api.convert).toHaveBeenCalledWith(4, [10], "lines");
    await userEvent.click(screen.getByRole("button", { name: "Cut letters" }));
    expect(await screen.findByText(/not converted yet/)).toBeInTheDocument();
    expect(localStorage.getItem("text-mode")).toBe("letters");
  });
});
