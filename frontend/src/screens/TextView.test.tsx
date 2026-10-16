import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, PageText } from "../api";
import TextView, { plainLines } from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), proofread: vi.fn(), proofreadStats: vi.fn(), labelSamples: vi.fn(),
    checkLabel: vi.fn(), split: vi.fn(), join: vi.fn(), deleteSamples: vi.fn(), undo: vi.fn(), bookWholeLines: vi.fn() } };
});

// these tests: the cut-letter view, hidden unless the book's setting shows it (C19)
const book = { id: 4, job: null, settings: { show_cut_letters: true } } as unknown as Book;
const letter = (id: number, dev: string, guj: string, x: number, over = {}) => ({
  sample_id: id, box: [x, 10, 20, 30] as [number, number, number, number], text_dev: dev, text_guj: guj, conf: 0.99,
  source: "both" as const, uncertain: false, space: false, readings: [["tesseract", dev, 98], ["groups", dev, 0.2]] as [string, string, number][],
  ...over,
});
const text: PageText = {
  page_id: 9, text_dev: "नार\nका", text_guj: "નાર\nકા", uncertain: 2, uncertain_tesseract: 1, readers: "tesseract+groups",
  converted_at: null,
  lines: [
    [letter(1, "ना", "ના", 10), letter(2, "र", "ર", 40, { uncertain: true, conf: 0.4, source: "tesseract",
      readings: [["tesseract", "र", 92], ["groups", "व", 0.3]], t_text_dev: "र", t_text_guj: "ર", t_conf: 0.74, t_uncertain: false })],
    [letter(3, "का", "કા", 10, { space: false }), letter(4, "", "", 40, { uncertain: true, conf: 0, source: "none", readings: [] })],
  ],
};

/** A letter of the text, aligned under its line (not the copy in the letter editor). */
const letterEl = (t: string) =>
  [...document.querySelectorAll(".aligned-akshara")].find((e) => e.textContent === t) as HTMLElement;

describe("TextView", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "page-0001.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/9", part: "read", number: 1 },
      { id: 10, file: "page-0002.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/10", part: "read", number: 2 },
    ]);
    vi.mocked(api.bookTexts).mockResolvedValue([{ page_id: 9, uncertain: 1, converted_at: null }]);
    vi.mocked(api.pageText).mockResolvedValue(text);
    vi.mocked(api.proofreadStats).mockResolvedValue({ lines: 0, chars: 0, cer: null, cer_tesseract: null });
    localStorage.setItem("text-mode", "letters");
    localStorage.removeItem("text-page-style");
    localStorage.removeItem("text-aligned");                                 // these tests: the cut-letter view
    vi.mocked(api.checkLabel).mockImplementation(async (t: string) => ({ ok: true, devanagari: t === "ળ" ? "ळ" : t, gujarati: t,
      codepoints: "", used_by: [] }) as never);
    window.location.hash = "";
  });

  it("shows the text beside the page, uncertain letters marked on both", async () => {
    localStorage.setItem("text-readers", "both");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(lines).getByText("ર")).toBeInTheDocument());
    expect(within(lines).getByText("ર")).toHaveClass("uncertain");
    expect(within(lines).getByText("?")).toHaveClass("unknown");
    expect(document.querySelectorAll(".line-crop .text-box.uncertain")).toHaveLength(2);
    await userEvent.click(within(lines).getByText("ર"));
    expect(screen.getByText(/Tesseract: र \(92\) · your groups: व \(0.3\)/)).toBeInTheDocument();
    expect(document.querySelector(".line-crop .text-box.selected")).not.toBeNull();
    expect(screen.getByText("1 of 2 converted")).toBeInTheDocument();
  });

  it("switches layout and script, and links the downloads with the chosen marker", async () => {
    localStorage.removeItem("text-readers");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await screen.findByText("ર");
    await userEvent.click(screen.getByRole("button", { name: "Line by line" }));
    expect(document.querySelector(".text-view")).toHaveClass("line");
    expect(screen.getByLabelText("Line on the page")).toBeInTheDocument();
    expect(screen.getByText("Line 1 of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next line" }));
    expect(screen.getByText("Line 2 of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Whole page" }));
    await userEvent.click(screen.getByRole("button", { name: "देवनागरी" }));
    expect(screen.getByText("र")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Uncertain letters in downloads"), "guess");
    const word = screen.getByRole("link", { name: "Page Word" });
    expect(word.getAttribute("href")).toMatch(/^\/files\/texts\/4\?format=docx&script=devanagari&marker=guess&readers=tesseract&page_id=9/);
    expect(screen.getByRole("link", { name: ".txt" }).getAttribute("href")).not.toMatch(/page_id/);   // whole book
    // the page images (not the text) as a PDF: this page, or all pages
    expect(screen.getByRole("link", { name: "This page" }).getAttribute("href")).toMatch(/^\/files\/page-images\/4\?part=read&page_id=9&/);
    expect(screen.getByRole("link", { name: /^All \d+ pages$/ }).getAttribute("href")).toMatch(/^\/files\/page-images\/4\?part=read&token=/);
  });

  it("shows Tesseract alone, or with the groups' second opinion", async () => {
    localStorage.removeItem("text-readers");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(lines).getByText("ર")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Tesseract only" })).toHaveClass("active");      // the default
    expect(within(lines).getByText("ર")).not.toHaveClass("uncertain");                        // Tesseract was sure
    expect(screen.getByText(/1 uncertain letters/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tesseract + your groups" }));
    expect(within(lines).getByText("ર")).toHaveClass("uncertain");                            // the groups disagree
    expect(screen.getByText(/2 uncertain letters/)).toBeInTheDocument();
    expect(localStorage.getItem("text-readers")).toBe("both");
  });

  it("converts a page that is not converted yet", async () => {
    vi.mocked(api.convert).mockResolvedValue({ id: "j", book_id: 4, kind: "convert", status: "running", done: 0, total: 1,
      current: "", pages: [], result: null, error: "", seconds: 0 });
    render(<TextView book={book} pageId={10} onChanged={() => {}} />);
    expect(await screen.findByText(/not converted yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Convert this page" }));
    expect(api.convert).toHaveBeenCalledWith(4, [10]);
    expect(await screen.findByText(/Converting pages into text/)).toBeInTheDocument();
  });

  it("corrects a letter by labelling its sample", async () => {
    const ok = { action_id: 1, kind: "label_samples", undo: 1, redo: 0 } as never;
    vi.mocked(api.labelSamples).mockResolvedValue(ok);
    vi.mocked(api.deleteSamples).mockResolvedValue(ok);
    const corrected = structuredClone(text);
    corrected.lines[0][1] = { ...corrected.lines[0][1], text_dev: "ळ", text_guj: "ળ", source: "label", uncertain: false, read_dev: "र" };
    corrected.corrected = 1;
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(lines).getByText("ર")).toBeInTheDocument());
    await userEvent.click(within(lines).getByText("ર"));
    vi.mocked(api.pageText).mockResolvedValue(corrected);
    const editor = screen.getByLabelText("Letter");
    const input = within(editor).getByLabelText("Label");
    await userEvent.clear(input);
    await userEvent.type(input, "ળ");
    await waitFor(() => expect(within(editor).getByRole("button", { name: "Correct" })).toBeEnabled());
    await userEvent.click(within(editor).getByRole("button", { name: "Correct" }));
    expect(api.labelSamples).toHaveBeenCalledWith(4, [2], "ળ");
    await waitFor(() => expect(letterEl("ળ")).toBeInTheDocument());
    expect(screen.getByText(/corrected by you \(read as र\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 letters corrected/)).toBeInTheDocument();
    await userEvent.click(within(editor).getByRole("button", { name: "Not a letter" }));
    expect(api.deleteSamples).toHaveBeenCalledWith(4, [2]);
  });

  it("marks a line proofread and shows the measurement", async () => {
    vi.mocked(api.proofreadStats).mockResolvedValue({ lines: 3, chars: 100, cer: 0.042, cer_tesseract: 0.08 });
    vi.mocked(api.proofread).mockResolvedValue({ ...text, line_states: ["proofread", ""], proofread: 1 });
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await screen.findByLabelText("Line 1 not proofread");
    expect(screen.getByLabelText("Measured")).toHaveTextContent("3 proofread lines: 4.2% of the characters were read wrong (Tesseract alone 8.0%)");
    await userEvent.click(screen.getByLabelText("Line 1 not proofread"));
    expect(api.proofread).toHaveBeenCalledWith(9, 0, true);
    expect(await screen.findByLabelText("Line 1 proofread")).toHaveClass("done");
    expect(screen.getByText(/1 of 2 lines proofread/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Line 1 proofread"));
    expect(api.proofread).toHaveBeenLastCalledWith(9, 0, false);
  });

  it("joins a letter with the next and moves between uncertain letters", async () => {
    vi.mocked(api.join).mockResolvedValue({ action_id: 2, kind: "join", undo: 1, redo: 0, sample: { id: 7, page_id: 9, box: [], source: "joined" } } as never);
    localStorage.setItem("text-readers", "both");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Lines");
    await waitFor(() => expect(within(lines).getByText("ના")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Next uncertain ▶" }));
    expect(letterEl("ર")).toHaveClass("selected");
    await userEvent.click(screen.getByRole("button", { name: "Next uncertain ▶" }));
    expect(letterEl("?")).toHaveClass("selected");
    await userEvent.click(letterEl("ના"));
    await userEvent.click(screen.getByRole("button", { name: "Join with the next" }));
    expect(api.join).toHaveBeenCalledWith(4, [1, 2]);
  });

  it("names the letter checker when the page was read with it", async () => {
    localStorage.setItem("text-readers", "both");
    const withReader = structuredClone(text);
    withReader.readers = "tesseract+reader+groups";
    withReader.lines[0][1].readings = [["tesseract", "र", 92], ["reader", "व", 0.97], ["groups", "व", 0.3]];
    vi.mocked(api.pageText).mockResolvedValue(withReader);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await waitFor(() => expect(letterEl("ર")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Tesseract + your checker and groups" })).toHaveClass("active");
    expect(screen.getByText(/read by Tesseract, your letter checker and your groups/)).toBeInTheDocument();
    await userEvent.click(letterEl("ર"));
    expect(screen.getByText(/Tesseract: र \(92\) · your letter checker: व \(97%\) · your groups: व \(0.3\)/)).toBeInTheDocument();
  });

  it("moves between letters and lines with the arrow keys", async () => {
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await waitFor(() => expect(letterEl("ના")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(letterEl("ના")).toHaveClass("selected");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(letterEl("ર")).toHaveClass("selected");
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(letterEl("કા")).toHaveClass("selected");          // the first letter of line 2
    fireEvent.keyDown(window, { key: "ArrowUp" });
    expect(letterEl("ના")).toHaveClass("selected");
    await waitFor(() => expect(api.checkLabel).toHaveBeenCalled());               // the editor's label check is done
  });

  it("writes plain lines for the picture and the PDF", () => {
    expect(plainLines(text, "gujarati")).toEqual(["નાર", "કા?"]);
  });
});

describe("TextView without the Cut letters setting", () => {
  it("hides Cut letters and opens Whole lines instead, even when it was the last choice", async () => {
    vi.mocked(api.pages).mockResolvedValue([]);
    vi.mocked(api.bookWholeLines).mockResolvedValue([]);
    localStorage.setItem("text-mode", "letters");
    render(<TextView book={{ id: 4, job: null, settings: {} } as unknown as Book} pageId={null} onChanged={() => {}} />);
    expect(screen.queryByRole("button", { name: "Cut letters" })).toBeNull();
    expect(screen.getByRole("button", { name: "Whole lines (Tesseract)" })).toHaveClass("active");
    expect(screen.queryByRole("button", { name: /Convert/ })).toBeNull();
  });
});
