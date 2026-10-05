import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, Group, LabelSuggestion } from "../api";
import GroupView from "./GroupView";
import SamplesView from "./SamplesView";
import { bulkCandidates, isMixed, SuggestPanel } from "./Suggestions";
import { findTiles, group, renderView, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { tesseract: vi.fn(), accuracy: vi.fn(), suggest: vi.fn(), job: vi.fn(), cancelJob: vi.fn(),
    acceptSuggestions: vi.fn(), rejectSuggestion: vi.fn(), fixCuts: vi.fn(), labelSamples: vi.fn(), readAs: vi.fn(), merge: vi.fn(),
    groupSamples: vi.fn(), unsure: vi.fn(), checkLabel: vi.fn(), move: vi.fn(), label: vi.fn() } };
});
const ok = { undo: 1, redo: 0 };

const sug = (over: Partial<LabelSuggestion> = {}): LabelSuggestion => ({
  label_dev: "क", label_guj: "ક", share: 0.9, count: 18, read: 20, engine: "tesseract", merge_into: null, ...over,
});
const book = (over: Partial<Book> = {}): Book => ({
  id: 1, name: "B", input_dir: "/p", writing: "printed", pages: 1, samples: 10, groups: 3, labelled: 0, unsure: 0,
  created_at: null, updated_at: null, captured_at: null, settings: { bulk_accept_share: 0.9 }, undo: 0, redo: 0,
  job: null, ocr_runs: [], ...over,
});
const withRun = (over: Partial<Book> = {}) =>
  book({ ocr_runs: [{ engine: "tesseract", finished_at: "2026-10-05T10:00:00+00:00",
    result: { samples: 100, samples_matched: 75, groups_with_suggestion: 2 } }], ...over });

describe("suggestion helpers", () => {
  it("finds mixed groups and the groups to accept in bulk", () => {
    const mixed = group({ read: 10, readings: [{ label_dev: "ता", label_guj: "તા", count: 6 }, { label_dev: "ना", label_guj: "ના", count: 3 }] });
    const clean = group({ read: 10, readings: [{ label_dev: "क", label_guj: "ક", count: 9 }, { label_dev: "ख", label_guj: "ખ", count: 1 }] });
    expect([isMixed(mixed), isMixed(clean)]).toEqual([true, false]);
    const gs: Group[] = [
      group({ id: 1, suggestion: sug({ share: 0.95 }) }),
      group({ id: 2, suggestion: sug({ share: 0.8 }) }),
      group({ id: 3, suggestion: sug({ share: 0.99, merge_into: { id: 9, code: "g0009" } }) }),
      group({ id: 4, suggestion: sug({ share: 0.99 }), locked: true }),
      group({ id: 5, suggestion: null }),
    ];
    expect(bulkCandidates(gs, 0.9).map((g) => g.id)).toEqual([1]);
    expect(bulkCandidates(gs, 0.8).map((g) => g.id)).toEqual([1, 2]);
  });
});

describe("SuggestPanel", () => {
  beforeEach(() => {
    vi.mocked(api.tesseract).mockResolvedValue({ ok: true, langs_needed: "script/Devanagari" });
    vi.mocked(api.acceptSuggestions).mockResolvedValue(ok);
  });

  it("starts reading a printed book and follows the job", async () => {
    const onRead = vi.fn();
    vi.mocked(api.suggest).mockResolvedValue({ id: "j", book_id: 1, kind: "suggest", status: "running", done: 0, total: 9,
      current: "", pages: [], result: null, error: "", seconds: 0 });
    renderView((ctx) => <SuggestPanel book={book()} ctx={ctx} onRead={onRead} />);
    const start = await screen.findByRole("button", { name: "Suggest labels (Tesseract)" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    expect(api.suggest).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Reading lines: 0 of 9")).toBeInTheDocument();
  });

  it("is a 'try' on handwritten books and explains why", async () => {
    renderView((ctx) => <SuggestPanel book={book({ writing: "handwritten" })} ctx={ctx} onRead={() => {}} />);
    expect(await screen.findByRole("button", { name: "Try Tesseract" })).toBeInTheDocument();
    expect(screen.getByText(/about a third of its letters are wrong/)).toBeInTheDocument();
  });

  it("is disabled with the reason when Tesseract is missing", async () => {
    vi.mocked(api.tesseract).mockResolvedValue({ ok: false, error: "Tesseract is not installed. See docs/INSTALL_TESSERACT.md.",
      langs_needed: "script/Devanagari" });
    renderView((ctx) => <SuggestPanel book={book()} ctx={ctx} onRead={() => {}} />);
    expect(await screen.findByText(/Tesseract is not installed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suggest labels (Tesseract)" })).toBeDisabled();
  });

  it("accepts all suggestions above the share after asking, as one action", async () => {
    const gs = [group({ id: 1, suggestion: sug({ share: 0.95 }) }), group({ id: 2, suggestion: sug({ label_dev: "ख", label_guj: "ખ", share: 0.7 }) })];
    const { act } = renderView((ctx) => <SuggestPanel book={withRun()} ctx={ctx} onRead={() => {}} />, gs);
    expect(screen.getByText(/75 of 100 letters/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept 1 with ≥" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Label 1 group with their suggested labels?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Label them" }));
    expect(act).toHaveBeenCalled();
    expect(api.acceptSuggestions).toHaveBeenCalledWith(1, [{ group_id: 1, label_dev: "क" }]);
  });

  it("fixes cuts on printed books after asking, and not on handwritten ones", async () => {
    vi.mocked(api.fixCuts).mockResolvedValue({ id: "j2", book_id: 1, kind: "fix_cuts", status: "running", done: 0,
      total: 9, current: "", pages: [], result: null, error: "", seconds: 0 });
    const { unmount } = renderView((ctx) => <SuggestPanel book={withRun()} ctx={ctx} onRead={() => {}} />);
    const fix = screen.getByRole("button", { name: "Fix cuts with Tesseract" });
    await waitFor(() => expect(fix).toBeEnabled());
    await userEvent.click(fix);
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Fix cuts" }));
    expect(api.fixCuts).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Checking cuts: 0 of 9")).toBeInTheDocument();
    unmount();
    renderView((ctx) => <SuggestPanel book={withRun({ writing: "handwritten" })} ctx={ctx} onRead={() => {}} />);
    expect(screen.queryByRole("button", { name: "Fix cuts with Tesseract" })).toBeNull();
  });

  it("shows how the suggestions compare with the labels", async () => {
    vi.mocked(api.accuracy).mockResolvedValue({ labelled: 27, suggested: 13, right: 13, none: 14,
      bands: [{ band: "90% or more", right: 12, wrong: 0 }, { band: "75 to 90%", right: 1, wrong: 0 }, { band: "below 75%", right: 0, wrong: 0 }],
      wrong: [] });
    renderView((ctx) => <SuggestPanel book={withRun({ labelled: 27 })} ctx={ctx} onRead={() => {}} />);
    expect(await screen.findByText("Checked against your labels: 13 of 13 right")).toBeInTheDocument();
  });
});

describe("suggestions on a group", () => {
  beforeEach(() => {
    vi.mocked(api.groupSamples).mockResolvedValue({ total: 3, offset: 0, samples: [
      sample(1, { reading: { label_dev: "क", label_guj: "ક", confidence: 97, engine: "tesseract" } }),
      sample(2, { reading: { label_dev: "ब", label_guj: "બ", confidence: 96, engine: "tesseract" } }),
      sample(3),
    ] });
    for (const f of [api.acceptSuggestions, api.rejectSuggestion, api.merge]) vi.mocked(f).mockResolvedValue(ok);
    vi.mocked(api.checkLabel).mockResolvedValue({ ok: true, devanagari: "क", gujarati: "ક" });
  });

  it("accepts and rejects the suggestion, and badges samples read otherwise", async () => {
    renderView((ctx) => <GroupView group={group({ suggestion: sug() })} ctx={ctx} />);
    const chip = screen.getByRole("group", { name: "Suggested label" });
    expect(chip).toHaveTextContent("18 of 20 read (90%)");
    await userEvent.click(within(chip).getByRole("button", { name: "Accept" }));
    expect(api.acceptSuggestions).toHaveBeenCalledWith(1, [{ group_id: 5, label_dev: "क" }]);
    await userEvent.click(within(chip).getByRole("button", { name: "Reject" }));
    expect(api.rejectSuggestion).toHaveBeenCalledWith(1, 5, "क");
    await findTiles();
    expect(screen.getAllByTitle(/^Read as/).map((b) => b.textContent)).toEqual(["બ"]);   // only the one read otherwise
  });

  it("offers a merge when another group has the label, and fills the picker on Change", async () => {
    renderView((ctx) => <GroupView group={group({ suggestion: sug({ merge_into: { id: 9, code: "g0009" } }) })} ctx={ctx} />);
    const chip = screen.getByRole("group", { name: "Suggested label" });
    await userEvent.click(within(chip).getByRole("button", { name: "Merge into g0009" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Merge" }));
    expect(api.merge).toHaveBeenCalledWith(1, 9, [5]);
    await userEvent.click(within(chip).getByRole("button", { name: "Change…" }));
    expect(screen.getByDisplayValue("ક")).toBeInTheDocument();
  });

  it("selects the samples of one reading to split a mixed group", async () => {
    vi.mocked(api.readAs).mockResolvedValue({ ids: [2] });
    const mixed = group({ read: 10, readings: [{ label_dev: "क", label_guj: "ક", count: 6 }, { label_dev: "ब", label_guj: "બ", count: 4 }] });
    renderView((ctx) => <GroupView group={mixed} ctx={ctx} />);
    expect(screen.getByText(/Mixed readings/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^બ/ }));
    expect(api.readAs).toHaveBeenCalledWith(5, "ब");
    expect(await screen.findByText("1 selected")).toBeInTheDocument();
  });
});

describe("readings of unsure samples", () => {
  it("puts a sample under its reading's label", async () => {
    vi.mocked(api.unsure).mockResolvedValue({ total: 1, offset: 0, samples: [
      sample(7, { group_id: null, reading: { label_dev: "क", label_guj: "ક", confidence: 97, engine: "tesseract" } }),
    ] });
    vi.mocked(api.labelSamples).mockResolvedValue(ok);
    renderView((ctx) => <SamplesView kind="unsure" ctx={ctx} />);
    await userEvent.click(await screen.findByTitle(/^Tesseract read ક/));
    expect(api.labelSamples).toHaveBeenCalledWith(1, [7], "क");
  });
});
