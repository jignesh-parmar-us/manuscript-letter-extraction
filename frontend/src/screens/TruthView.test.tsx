import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, TruthLine } from "../api";
import TruthView from "./TruthView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { truthProgress: vi.fn(), truthLines: vi.fn(), lineTesseract: vi.fn(), saveTruth: vi.fn() } };
});

const book = { id: 6 } as unknown as Book;
const line = (id: number, over: Partial<TruthLine> = {}): TruthLine => ({
  line_id: id, number: id, box: [0, 0, 100, 20], image: `/l/${id}`, truth_dev: null, truth_guj: null, ...over,
});

describe("TruthView", () => {
  beforeEach(() => {
    vi.mocked(api.truthProgress).mockResolvedValue({ pages: [{ page_id: 9, file: "Untitled-51.jpg", lines: 3, checked: 1 }],
      lines: 3, checked: 1 });
    vi.mocked(api.truthLines).mockResolvedValue([line(1, { truth_dev: "नारायण", truth_guj: "નારાયણ" }), line(2), line(3)]);
    vi.mocked(api.lineTesseract).mockImplementation(async (id: number) =>
      ({ line_id: id, text_dev: id === 2 ? "नबरा" : "जो", text_guj: id === 2 ? "નબરા" : "જો" }));
  });

  it("starts at the first unchecked line with Tesseract's reading, saves the correction and goes on", async () => {
    vi.mocked(api.saveTruth).mockResolvedValue({ line_id: 2, truth_dev: "नधरा", truth_guj: "નધરા" });
    render(<TruthView book={book} pageId={9} />);
    const input = await screen.findByLabelText("What the line says");
    await waitFor(() => expect(input).toHaveValue("નબરા"));                  // line 2: Tesseract's whole-line reading
    expect(screen.getByText("Line 2 of 3 · Untitled-51.jpg")).toBeInTheDocument();
    await userEvent.clear(input);
    await userEvent.type(input, "નધરા{Enter}");
    expect(api.saveTruth).toHaveBeenCalledWith(2, "નધરા", "नबरा");
    await waitFor(() => expect(screen.getByText(/Line 3 of 3/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText("What the line says")).toHaveValue("જો"));
    expect(screen.getByRole("button", { name: "✓ નધરા" })).toBeInTheDocument();     // marked in the list
  });

  it("shows a checked line's text and can uncheck it", async () => {
    vi.mocked(api.saveTruth).mockResolvedValue({ line_id: 1, truth_dev: null, truth_guj: null });
    render(<TruthView book={book} pageId={9} />);
    await userEvent.click(await screen.findByRole("button", { name: "✓ નારાયણ" }));
    await waitFor(() => expect(screen.getByLabelText("What the line says")).toHaveValue("નારાયણ"));
    await userEvent.click(screen.getByRole("button", { name: "Not checked" }));
    expect(api.saveTruth).toHaveBeenCalledWith(1, "", "जो");
  });
});
