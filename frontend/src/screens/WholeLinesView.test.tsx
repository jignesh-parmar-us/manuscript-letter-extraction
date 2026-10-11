import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, WholeLines } from "../api";
import TextView from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookWholeLines: vi.fn(), wholeLines: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), proofreadStats: vi.fn(), saveWholeLine: vi.fn() } };
});

const book = { id: 4, job: null } as unknown as Book;
const ak = (dev: string, guj: string, x: number, over = {}) =>
  ({ text_dev: dev, text_guj: guj, conf: 96, space: false, uncertain: false, box: [x, 20, 30, 40] as [number, number, number, number], ...over });
const text = (): WholeLines => ({
  page_id: 9, uncertain: 1, read_at: null,
  lines: [
    { line_id: 1, number: 1, box: [10, 10, 300, 60], text_dev: "नारायव भग", text_guj: "નારાયવ ભગ", edited_dev: "", edited_guj: "", reviewed: false,
      aksharas: [ak("ना", "ના", 10), ak("रा", "રા", 40), ak("य", "ય", 70), ak("व", "વ", 100, { conf: 60, uncertain: true, lm_dev: "ण", lm_guj: "ણ" }),
        ak("भ", "ભ", 150, { space: true }), ak("ग", "ગ", 180)] },
    { line_id: 2, number: 2, box: [10, 80, 300, 60], text_dev: "जो", text_guj: "જો", edited_dev: "", edited_guj: "", reviewed: false,
      aksharas: [ak("जो", "જો", 10)] },
  ],
});
const pages = [
  { id: 9, file: "page-0001.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 7, image: "/p/9", part: "read" as const, number: 1 },
  { id: 10, file: "page-0002.jpg", width: 400, height: 200, status: "OK", message: "", lines: 1, samples: 6, image: "/p/10", part: "read" as const, number: 2 },
];

describe("Whole lines", () => {
  beforeEach(() => {
    localStorage.removeItem("text-mode");
    localStorage.removeItem("text-layout");
    localStorage.removeItem("whole-lines-lm");
    vi.mocked(api.pages).mockResolvedValue(pages as never);
    vi.mocked(api.bookWholeLines).mockResolvedValue([{ page_id: 9, lines: 2 }]);
    vi.mocked(api.wholeLines).mockResolvedValue(text());
  });

  it("shows Tesseract's reading with the language model's corrections and the clicked akshara on the page", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    expect(screen.getByRole("button", { name: "Whole lines (Tesseract)" })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Whole page" })).toHaveClass("active");
    const pane = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(pane).getByText("ણ")).toHaveClass("lm"));
    expect(screen.getByRole("link", { name: "Page .txt" }).getAttribute("href")).toMatch(/readers=lines_lm&page_id=9/);
    await userEvent.click(screen.getByLabelText("With the language model"));
    expect(within(pane).getByText("વ")).toHaveClass("uncertain");
    await userEvent.click(within(pane).getByText("વ"));
    expect(screen.getByText(/Tesseract: વ \(60\) · the language model: ણ/)).toBeInTheDocument();
    expect(document.querySelector(".line-crop .text-box.selected")).not.toBeNull();   // the akshara on its line
  });

  it("moves through the aksharas and lines with the arrow keys", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const pane = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(pane).getByText("ના")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(within(pane).getByText("ના")).toHaveClass("selected");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(within(pane).getByText("રા")).toHaveClass("selected");
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(within(pane).getByText("જો")).toHaveClass("selected");
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(within(pane).getByText("ગ")).toHaveClass("selected");                // back to the end of line 1
  });

  it("corrects a line and marks it reviewed", async () => {
    vi.mocked(api.saveWholeLine).mockResolvedValueOnce({ line_id: 1, edited_dev: "नारायण भग", edited_guj: "નારાયણ ભગ", reviewed: false })
      .mockResolvedValueOnce({ line_id: 1, edited_dev: "नारायण भग", edited_guj: "નારાયણ ભગ", reviewed: true });
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Correct line 1" }));
    const input = screen.getByLabelText("Correct the line");
    await userEvent.clear(input);
    await userEvent.type(input, "નારાયણ ભગ{Enter}");
    expect(api.saveWholeLine).toHaveBeenCalledWith(1, { text: "નારાયણ ભગ", shown: "नारायण भग" });
    expect(await screen.findByText("નારાયણ ભગ")).toHaveClass("edited");
    await userEvent.click(screen.getByRole("button", { name: "Line 1 not reviewed" }));
    expect(api.saveWholeLine).toHaveBeenLastCalledWith(1, { reviewed: true, shown: "नारायण भग" });
    expect(await screen.findByRole("button", { name: "Line 1 reviewed" })).toHaveClass("done");
  });

  it("shows one line at a time, with the letters on top of the screen", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Line by line" }));
    expect(await screen.findByText("Line 1 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Line on the page")).toBeInTheDocument();
    expect(screen.getByLabelText("Correct the line")).toHaveValue("નારાયણ ભગ");   // with the language model
    await userEvent.click(screen.getByRole("button", { name: "Letters…" }));
    expect(document.body.querySelector(".palette-overlay")).not.toBeNull();         // on top, not in the panel
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(document.body.querySelector(".palette-overlay")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Next line" }));
    expect(screen.getByText("Line 2 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Correct the line")).toHaveValue("જો");
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
