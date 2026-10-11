import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, PageText } from "../api";
import TextView, { plainLines } from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn(), proofread: vi.fn(), proofreadStats: vi.fn(), labelSamples: vi.fn(),
    checkLabel: vi.fn(), split: vi.fn(), join: vi.fn(), deleteSamples: vi.fn(), undo: vi.fn() } };
});

const book = { id: 4, job: null } as unknown as Book;
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

/** The text's lines only (the letter editor below them shows the selected letter too). */
const textLines = () => document.querySelector(".text-lines") as HTMLElement;

describe("TextView", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "page-0001.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/9", part: "read", number: 1 },
      { id: 10, file: "page-0002.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/10", part: "read", number: 2 },
    ]);
    vi.mocked(api.bookTexts).mockResolvedValue([{ page_id: 9, uncertain: 1, converted_at: null }]);
    vi.mocked(api.pageText).mockResolvedValue(text);
    vi.mocked(api.proofreadStats).mockResolvedValue({ lines: 0, chars: 0, cer: null, cer_tesseract: null });
    localStorage.setItem("text-mode", "letters");                                 // these tests: the cut-letter view
    vi.mocked(api.checkLabel).mockImplementation(async (t: string) => ({ ok: true, devanagari: t === "ળ" ? "ळ" : t, gujarati: t,
      codepoints: "", used_by: [] }) as never);
    window.location.hash = "";
  });

  it("shows the text beside the page, uncertain letters marked on both", async () => {
    localStorage.setItem("text-readers", "both");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Text");
    await waitFor(() => expect(within(lines).getByText("ર")).toBeInTheDocument());
    expect(within(lines).getByText("ર")).toHaveClass("uncertain");
    expect(within(lines).getByText("?")).toHaveClass("unknown");
    expect(screen.getByLabelText("Page").querySelectorAll(".text-box.uncertain")).toHaveLength(2);
    await userEvent.click(within(lines).getByText("ર"));
    expect(screen.getByText(/Tesseract: र \(92\) · your groups: व \(0.3\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Page").querySelector(".text-box.selected")).not.toBeNull();
    expect(screen.getByText("1 of 2 converted")).toBeInTheDocument();
  });

  it("switches layout and script, and links the downloads with the chosen marker", async () => {
    localStorage.removeItem("text-readers");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await screen.findByText("ર");
    await userEvent.click(screen.getByRole("button", { name: "One above the other" }));
    expect(document.querySelector(".text-view")).toHaveClass("stacked");
    await userEvent.click(screen.getByRole("button", { name: "देवनागरी" }));
    expect(screen.getByText("र")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Uncertain letters in downloads"), "guess");
    const word = screen.getByRole("link", { name: "Page Word" });
    expect(word.getAttribute("href")).toMatch(/^\/files\/texts\/4\?format=docx&script=devanagari&marker=guess&readers=tesseract&page_id=9/);
    expect(screen.getByRole("link", { name: ".txt" }).getAttribute("href")).not.toMatch(/page_id/);   // whole book
  });

  it("shows Tesseract alone, or with the groups' second opinion", async () => {
    localStorage.removeItem("text-readers");
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    const lines = await screen.findByLabelText("Text");
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
    const lines = await screen.findByLabelText("Text");
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
    await waitFor(() => expect(within(textLines()).getByText("ળ")).toBeInTheDocument());
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
    const lines = await screen.findByLabelText("Text");
    await waitFor(() => expect(within(lines).getByText("ના")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Next uncertain ▶" }));
    expect(within(textLines()).getByText("ર")).toHaveClass("selected");
    await userEvent.click(screen.getByRole("button", { name: "Next uncertain ▶" }));
    expect(within(textLines()).getByText("?")).toHaveClass("selected");
    await userEvent.click(within(textLines()).getByText("ના"));
    await userEvent.click(screen.getByRole("button", { name: "Join with the next" }));
    expect(api.join).toHaveBeenCalledWith(4, [1, 2]);
  });

  it("names the letter reader when the page was read with it", async () => {
    localStorage.setItem("text-readers", "both");
    const withReader = structuredClone(text);
    withReader.readers = "tesseract+reader+groups";
    withReader.lines[0][1].readings = [["tesseract", "र", 92], ["reader", "व", 0.97], ["groups", "व", 0.3]];
    vi.mocked(api.pageText).mockResolvedValue(withReader);
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await waitFor(() => expect(within(textLines()).getByText("ર")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Tesseract + your reader and groups" })).toHaveClass("active");
    expect(screen.getByText(/read by Tesseract, your letter reader and your groups/)).toBeInTheDocument();
    await userEvent.click(within(textLines()).getByText("ર"));
    expect(screen.getByText(/Tesseract: र \(92\) · your letter reader: व \(97%\) · your groups: व \(0.3\)/)).toBeInTheDocument();
  });

  it("writes plain lines for the picture and the PDF", () => {
    expect(plainLines(text, "gujarati")).toEqual(["નાર", "કા?"]);
  });
});
