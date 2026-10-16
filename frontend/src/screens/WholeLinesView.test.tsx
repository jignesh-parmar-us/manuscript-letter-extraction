import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, WholeLines } from "../api";
import TextView from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookWholeLines: vi.fn(), wholeLines: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), proofreadStats: vi.fn(), saveWholeLine: vi.fn(),
    lineSearch: vi.fn(), lineSearchReader: vi.fn(), lineSearchMeasure: vi.fn(), lineSearchTrain: vi.fn() } };
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
    localStorage.removeItem("text-page-style");
    localStorage.removeItem("text-aligned");
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

  it("shows each line as its own line image, without the next line's ink", async () => {
    const t = text();
    t.lines[0].image = "/files/books/4/read/lines/p_L01.png";
    t.lines[0].image_box = [4, 4, 312, 72];
    vi.mocked(api.wholeLines).mockResolvedValue(t);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Line by line" }));
    const crop = await screen.findByLabelText("Line on the page");
    expect(crop.querySelector("img")?.getAttribute("src")).toBe("/files/books/4/read/lines/p_L01.png");
    expect(crop.style.aspectRatio).toBe("312 / 72");
    await userEvent.click(screen.getByRole("button", { name: "Next line" }));
    expect(screen.getByLabelText("Line on the page").querySelector("img")?.getAttribute("src")).toBe("/p/9");   // no line image: the page
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

  it("shows one line at a time, with the letters under the correction box", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Line by line" }));
    expect(await screen.findByText("Line 1 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Line on the page")).toBeInTheDocument();
    expect(screen.getByLabelText("Correct the line")).toHaveValue("નારાયણ ભગ");   // with the language model
    await userEvent.click(screen.getByRole("button", { name: "Letters…" }));
    expect(document.body.querySelector(".palette-overlay")).toBeNull();            // in the flow: it never covers the box
    expect(screen.getByRole("group", { name: "Letters" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "ક" }));
    expect(screen.getByLabelText("Correct the line")).toHaveValue("નારાયણ ભગક");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("group", { name: "Letters" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Next line" }));
    expect(screen.getByText("Line 2 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Correct the line")).toHaveValue("જો");
  });

  it("shows the page as a page or as line strips, with or without the aligned text", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await screen.findByLabelText("Lines");
    expect(document.querySelectorAll(".aligned-text")).toHaveLength(2);           // line strips, aligned (the default)
    await userEvent.click(screen.getByLabelText("Aligned text"));
    expect(document.querySelectorAll(".aligned-text")).toHaveLength(0);
    expect(document.querySelectorAll(".line-crop")).toHaveLength(2);              // still a strip per line, plain text
    await userEvent.click(screen.getByRole("button", { name: "As a page" }));
    expect(screen.getByLabelText("Page").querySelector(".text-page-image")).not.toBeNull();
    expect(document.querySelectorAll(".line-crop")).toHaveLength(0);
    expect(screen.queryByLabelText("Aligned text")).toBeNull();                    // no strips: no switch
    await userEvent.click(screen.getByRole("button", { name: "Line by line" }));
    expect(screen.queryByRole("button", { name: "As a page" })).toBeNull();
    expect(document.querySelectorAll(".aligned-text")).toHaveLength(0);           // aligned text still off
    expect(screen.getByLabelText("Correct the line")).toBeInTheDocument();
  });

  it("shows our reader's second opinion in Tesseract's view", async () => {
    const t = text();
    t.lines[0].searched = true;
    t.lines[0].aksharas[1] = { ...t.lines[0].aksharas[1], uncertain: true, search_dev: "य", search_guj: "ય" };
    vi.mocked(api.wholeLines).mockResolvedValue(t);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const pane = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(pane).getByText("રા")).toHaveClass("uncertain"));
    expect(screen.getByText(/second opinion on 1 of 2 lines/)).toBeInTheDocument();
    await userEvent.click(within(pane).getByText("રા"));
    expect(screen.getByText(/our reader: ય/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Second opinion" })).toBeNull();     // in its own tab now
  });

  it("shows our reader's own reading, retrains it and measures it", async () => {
    const t = text();
    t.lines[0].searched = true;
    t.lines[0].aksharas[3] = { ...t.lines[0].aksharas[3], text_dev: "ण", text_guj: "ણ", conf: null, lm_dev: undefined,
      lm_guj: undefined, other_dev: "व", other_guj: "વ" };
    vi.mocked(api.wholeLines).mockResolvedValue(t);
    vi.mocked(api.lineSearchReader).mockResolvedValue({
      reader: { letters: 8946, labels: 412, lines: 99, trained_at: "2026-10-12T05:58:50Z", seconds: 400, changed: true },
      measure: { measured_at: "2026-10-12T09:00:00Z", folds: 4, pages: 8, lines: 73, chars: 6677,
        cer: { ours: 10.2, tesseract: 5.1, tesseract_lm: 4.45 }, marked: 19.4, mistakes: 277, caught: 244,
        line_results: [{ page: "Untitled-15.jpg", line: 1, truth: "नारायण", ours: "नारायण", tesseract: "नारायव", tesseract_lm: "नारायण",
          chars: 6, wrong: { ours: 0, tesseract: 1, tesseract_lm: 0 } }] },
    });
    const job = { id: "j", book_id: 4, status: "running", done: 0, total: 1, current: "", pages: [], result: null, error: "", seconds: 0 };
    vi.mocked(api.lineSearch).mockResolvedValue({ ...job, kind: "line_search" } as never);
    vi.mocked(api.lineSearchMeasure).mockResolvedValue({ ...job, kind: "line_search_measure" } as never);
    vi.mocked(api.lineSearchTrain).mockResolvedValue({ ...job, kind: "line_search_train" } as never);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Whole lines (our reader)" }));
    const pane = await screen.findByLabelText("Lines");
    expect(api.wholeLines).toHaveBeenLastCalledWith(9, "search");
    expect(api.bookWholeLines).toHaveBeenCalledWith(4, "search");
    expect(screen.queryByLabelText("With the language model")).toBeNull();
    expect(screen.getByRole("link", { name: "Page .txt" }).getAttribute("href")).toMatch(/readers=search&page_id=9/);
    expect(screen.getByRole("link", { name: "Page Word" }).getAttribute("href")).toMatch(/format=docx.*readers=search/);
    window.print = vi.fn();
    vi.mocked(api.wholeLines).mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Page PDF" }));
    expect(api.wholeLines).toHaveBeenCalledWith(9, "search");                    // the PDF prints this tab's reading
    await waitFor(() => expect(window.print).toHaveBeenCalled());
    await userEvent.click(within(pane).getByText("ણ"));
    expect(screen.getByText(/our reader · Tesseract: વ/)).toBeInTheDocument();
    expect(screen.getByText(/Reader trained on 8946 reviewed letters and 99 checked lines/)).toBeInTheDocument();
    expect(screen.getByText(/changed since: retrain/)).toBeInTheDocument();
    expect(screen.getByText(/our reader 10.2%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show the lines" }));
    expect(screen.getByText("Untitled-15.jpg · 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retrain" }));             // training only
    expect(api.lineSearchTrain).toHaveBeenCalledWith(4);
    expect(api.lineSearch).not.toHaveBeenCalled();
    expect(await screen.findByText(/Training our reader/)).toBeInTheDocument();
  });

  it("measures our reader on the checked lines", async () => {
    vi.mocked(api.lineSearchReader).mockResolvedValue({ reader: null, measure: null });
    vi.mocked(api.lineSearchMeasure).mockResolvedValue({ id: "j", book_id: 4, kind: "line_search_measure", status: "running",
      done: 0, total: 4, current: "", pages: [], result: null, error: "", seconds: 0 } as never);
    localStorage.setItem("text-mode", "search");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    expect(await screen.findByText(/No reader yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrain" })).toHaveClass("primary");    // no reader yet
    await userEvent.click(screen.getByRole("button", { name: "Measure" }));
    expect(api.lineSearchMeasure).toHaveBeenCalledWith(4);
    expect(await screen.findByText(/Measuring our reader/)).toBeInTheDocument();
  });

  it("a quick measure is marked as screening only and keeps the full one", async () => {
    const m = { measured_at: "2026-10-12T09:00:00Z", folds: 4, pages: 8, lines: 73, chars: 6677,
      cer: { ours: 10.2, tesseract: 5.1, tesseract_lm: 4.45 }, marked: 19.4, mistakes: 277, caught: 244, line_results: [] };
    vi.mocked(api.lineSearchReader).mockResolvedValue({ reader: null, measure: m,
      quick_measure: { ...m, measured_at: "2026-10-13T09:00:00Z", quick: true, tested_folds: 2, cer: { ...m.cer, ours: 9.0 } } });
    vi.mocked(api.lineSearchMeasure).mockResolvedValue({ id: "j", book_id: 4, kind: "line_search_measure", status: "running",
      done: 0, total: 2, current: "", pages: [], result: null, error: "", seconds: 0 } as never);
    localStorage.setItem("text-mode", "search");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const quick = await screen.findByLabelText("Quick measure");
    expect(within(quick).getByText(/2 of 4 groups of pages\): for screening only/)).toBeInTheDocument();
    expect(within(quick).getByText(/our reader 9%/)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Measure")).getByText(/our reader 10.2%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Quick measure" }));
    expect(api.lineSearchMeasure).toHaveBeenCalledWith(4, true);
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
  it("reads only the pages not read yet, with Tesseract and with our reader", async () => {
    const job = { id: "j", book_id: 4, status: "running", done: 0, total: 1, current: "", pages: [], result: null, error: "", seconds: 0 };
    vi.mocked(api.convert).mockResolvedValue({ ...job, kind: "convert" } as never);
    vi.mocked(api.lineSearch).mockResolvedValue({ ...job, kind: "line_search" } as never);
    vi.mocked(api.lineSearchReader).mockResolvedValue({ reader: null, measure: null });
    const { unmount } = render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Read unread pages (1)" }));
    expect(api.convert).toHaveBeenCalledWith(4, [10], "lines");                  // page 9 is read already
    unmount();
    localStorage.setItem("text-mode", "search");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Read unread pages (1)" }));
    expect(api.lineSearch).toHaveBeenCalledWith(4, [10]);
  });

  it("has nothing to read when every page is read", async () => {
    vi.mocked(api.bookWholeLines).mockResolvedValue([{ page_id: 9, lines: 2 }, { page_id: 10, lines: 1 }]);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    expect(await screen.findByRole("button", { name: "Read unread pages (0)" })).toBeDisabled();
  });
});
