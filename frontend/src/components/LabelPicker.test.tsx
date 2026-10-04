import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import LabelPicker, { toGujarati } from "./LabelPicker";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { checkLabel: vi.fn() } };
});

describe("LabelPicker", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.checkLabel).mockImplementation(async (text) =>
      text === "कम"
        ? { ok: false, error: "more than one letter: क + म" }
        : { ok: true, devanagari: "क्षि", gujarati: "ક્ષિ", code_points_gujarati: "U+0A95", category: "conjuncts" },
    );
  });
  afterEach(() => vi.useRealTimers());

  it("converts the palette letters to Gujarati like mapping.py", () => {
    expect(toGujarati("श्री")).toBe("શ્રી");
    expect(toGujarati("क्षि॥")).toBe("ક્ષિ॥");
  });

  it("builds a conjunct with a vowel sign from the palette in both scripts", async () => {
    render(<LabelPicker bookId={1} current={{ dev: "", guj: "" }} onSave={async () => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Letters…" }));
    await userEvent.click(screen.getByRole("button", { name: "देवनागरी" }));
    for (const key of ["क", "◌्", "ष", "◌ि"]) await userEvent.click(screen.getByRole("button", { name: key }));
    expect(screen.getByLabelText("Label")).toHaveValue("क्षि");
    await userEvent.click(screen.getByRole("button", { name: "Empty" }));
    await userEvent.click(screen.getByRole("button", { name: "ગુજરાતી" }));
    for (const key of ["શ", "◌્", "ર", "◌ી"]) await userEvent.click(screen.getByRole("button", { name: key }));
    expect(screen.getByLabelText("Label")).toHaveValue("શ્રી");
  });

  it("checks the label while typing and saves it", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<LabelPicker bookId={4} current={{ dev: "", guj: "" }} onSave={onSave} />);
    await userEvent.type(screen.getByLabelText("Label"), "ક્ષિ");
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(api.checkLabel).toHaveBeenLastCalledWith("ક્ષિ", 4);
    expect(await screen.findByText("conjuncts · U+0A95")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save label" }));
    expect(onSave).toHaveBeenCalledWith("ક્ષિ");
  });

  it("hides the letters once the label is saved, not when saving failed", async () => {
    const onSave = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(<LabelPicker bookId={1} current={{ dev: "", guj: "" }} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Letters…" }));
    await userEvent.click(screen.getByRole("button", { name: "ક" }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    await userEvent.click(await screen.findByRole("button", { name: "Save label" }));
    expect(screen.getByRole("button", { name: "Hide letters" })).toBeInTheDocument();   // refused: still open
    await userEvent.click(screen.getByRole("button", { name: "Save label" }));
    expect(screen.getByRole("button", { name: "Letters…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ક" })).not.toBeInTheDocument();
  });

  it("shows why a label is refused and does not save it", async () => {
    render(<LabelPicker bookId={1} current={{ dev: "", guj: "" }} onSave={async () => {}} />);
    await userEvent.type(screen.getByLabelText("Label"), "कम");
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(await screen.findByText("more than one letter: क + म")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save label" })).toBeDisabled();
  });

  it("takes a word, and offers a merge instead of a second group with the same label", async () => {
    vi.mocked(api.checkLabel).mockResolvedValue({
      ok: true, devanagari: "नमः", gujarati: "નમઃ", code_points_gujarati: "U+0AA8 U+0AAE U+0A83", category: "words",
      letters: 2, used_by: [{ id: 5, code: "g0005", locked: false, samples: 3 }, { id: 6, code: "g0006", locked: false, samples: 9 }],
    });
    const onSave = vi.fn(async () => {});
    const onMerge = vi.fn(async () => {});
    render(<LabelPicker bookId={1} groupId={5} current={{ dev: "", guj: "" }} onSave={onSave} onMerge={onMerge} />);
    await userEvent.type(screen.getByLabelText("Label"), "નમઃ");
    await act(async () => vi.advanceTimersByTime(300));
    expect(await screen.findByText(/words \(2 letters\)/)).toBeInTheDocument();
    expect(screen.getByText(/already the label of g0006 \(9\)\./)).toBeInTheDocument();   // its own group is not counted
    expect(screen.getByRole("button", { name: "Save label" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Merge into g0006" }));
    expect(onMerge).toHaveBeenCalledWith(expect.objectContaining({ id: 6 }));
    expect(onSave).not.toHaveBeenCalled();
  });

  it("for samples, says which group they go into, and refuses a locked one", async () => {
    vi.mocked(api.checkLabel).mockResolvedValue({
      ok: true, devanagari: "क", gujarati: "ક", category: "consonants", letters: 1,
      used_by: [{ id: 7, code: "g0007", locked: true, samples: 4 }],
    });
    render(<LabelPicker bookId={1} current={{ dev: "", guj: "" }} saveText="Label it" onSave={async () => {}} />);
    await userEvent.type(screen.getByLabelText("Label"), "ક");
    await act(async () => vi.advanceTimersByTime(300));
    expect(await screen.findByText(/g0007 with this label is locked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Label it" })).toBeDisabled();
  });
});
