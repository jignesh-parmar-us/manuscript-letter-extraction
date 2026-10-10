import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, PageText } from "../api";
import TextView, { plainLines } from "./TextView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { ...real.api, pages: vi.fn(), bookTexts: vi.fn(), pageText: vi.fn(), convert: vi.fn(),
    job: vi.fn(), cancelJob: vi.fn() } };
});

const book = { id: 4, job: null } as unknown as Book;
const letter = (id: number, dev: string, guj: string, x: number, over = {}) => ({
  sample_id: id, box: [x, 10, 20, 30] as [number, number, number, number], text_dev: dev, text_guj: guj, conf: 0.99,
  source: "both" as const, uncertain: false, space: false, readings: [["tesseract", dev, 98], ["groups", dev, 0.2]] as [string, string, number][],
  ...over,
});
const text: PageText = {
  page_id: 9, text_dev: "नार\nका", text_guj: "નાર\nકા", uncertain: 1, readers: "tesseract+groups", converted_at: null,
  lines: [
    [letter(1, "ना", "ના", 10), letter(2, "र", "ર", 40, { uncertain: true, conf: 0.4, source: "tesseract",
      readings: [["tesseract", "र", 92], ["groups", "व", 0.3]] })],
    [letter(3, "का", "કા", 10, { space: false }), letter(4, "", "", 40, { uncertain: true, conf: 0, source: "none", readings: [] })],
  ],
};

describe("TextView", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([
      { id: 9, file: "page-0001.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/9", part: "read", number: 1 },
      { id: 10, file: "page-0002.jpg", width: 400, height: 200, status: "OK", message: "", lines: 2, samples: 4, image: "/p/10", part: "read", number: 2 },
    ]);
    vi.mocked(api.bookTexts).mockResolvedValue([{ page_id: 9, uncertain: 1, converted_at: null }]);
    vi.mocked(api.pageText).mockResolvedValue(text);
    window.location.hash = "";
  });

  it("shows the text beside the page, uncertain letters marked on both", async () => {
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
    render(<TextView book={book} pageId={9} onChanged={() => {}} />);
    await screen.findByText("ર");
    await userEvent.click(screen.getByRole("button", { name: "One above the other" }));
    expect(document.querySelector(".text-view")).toHaveClass("stacked");
    await userEvent.click(screen.getByRole("button", { name: "देवनागरी" }));
    expect(screen.getByText("र")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Uncertain letters in downloads"), "guess");
    const word = screen.getByRole("link", { name: "Page Word" });
    expect(word.getAttribute("href")).toMatch(/^\/files\/texts\/4\?format=docx&script=devanagari&marker=guess&page_id=9/);
    expect(screen.getByRole("link", { name: ".txt" }).getAttribute("href")).not.toMatch(/page_id/);   // whole book
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

  it("writes plain lines for the picture and the PDF", () => {
    expect(plainLines(text, "gujarati")).toEqual(["નાર", "કા?"]);
  });
});
