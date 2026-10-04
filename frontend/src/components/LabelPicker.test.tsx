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

  it("shows why a label is refused and does not save it", async () => {
    render(<LabelPicker bookId={1} current={{ dev: "", guj: "" }} onSave={async () => {}} />);
    await userEvent.type(screen.getByLabelText("Label"), "कम");
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(await screen.findByText("more than one letter: क + म")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save label" })).toBeDisabled();
  });
});
