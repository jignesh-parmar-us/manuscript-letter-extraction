import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { backTo, goBack } from "../components/returnSpot";
import GroupView from "./GroupView";
import { findTiles, group, renderView, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { groupSamples: vi.fn(), move: vi.fn(), newGroup: vi.fn(), deleteSamples: vi.fn(),
    merge: vi.fn(), dissolve: vi.fn(), status: vi.fn(), variants: vi.fn(), label: vi.fn(), checkLabel: vi.fn(), labelSamples: vi.fn(),
    confirmSamples: vi.fn() } };
});
const ok = { undo: 1, redo: 0 };

describe("GroupView", () => {
  beforeEach(() => {
    window.location.hash = "";
    vi.mocked(api.groupSamples).mockResolvedValue({ total: 3, offset: 0, samples: [sample(1), sample(2), sample(3)] });
    for (const f of [api.move, api.deleteSamples, api.merge, api.status, api.label]) vi.mocked(f).mockResolvedValue(ok);
    vi.mocked(api.checkLabel).mockResolvedValue({} as never);              // the label box checks what is typed
  });

  it("says a group is System generated and how it is used, until a real letter joins it", async () => {
    const { unmount } = renderView((ctx) => <GroupView group={group({ samples: 6, generated: 6, label_guj: "ઘો" })} ctx={ctx} />);
    expect(await screen.findByRole("note")).toHaveTextContent("System generated");
    expect(screen.getByRole("note")).toHaveTextContent("only reviewed, they are used for training and reading");
    unmount();
    renderView((ctx) => <GroupView group={group({ samples: 7, generated: 6 })} ctx={ctx} />);
    await findTiles();
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByText("6 of its letters were made by the system; the rest are real letters.")).toBeInTheDocument();
  });

  it("outlines the possible mix-ups; moves them to their likely letters or marks them as no mix-up", async () => {
    vi.mocked(api.labelSamples).mockResolvedValue(ok);
    vi.mocked(api.confirmSamples).mockResolvedValue({ confirmed: 1 });
    const mix = (id: number, read: string, read_guj: string) => ({ sample_id: id, group_id: 5, group_code: "g0005", label: "व",
      read, label_guj: "વ", read_guj, prob: 0.97, reviewed: true, locked: false, sample: sample(id) });
    const refresh = vi.fn();
    renderView((ctx) => <GroupView group={group({ label_dev: "व", label_guj: "વ" })} ctx={ctx} />, [group()],
      { mixups: new Map([[1, mix(1, "ब", "બ")], [3, mix(3, "च", "ચ")]]), refresh });
    const tiles = await findTiles();
    expect(tiles.map((t) => t.classList.contains("mixup"))).toEqual([true, false, true]);
    expect(within(tiles[0]).getByText("બ?")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("2 possible mix-ups");
    await userEvent.click(screen.getByRole("button", { name: "Select the possible mix-ups" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Move to their likely letters (2)" }));
    expect(api.labelSamples).toHaveBeenCalledWith(1, [1], "ब");
    expect(api.labelSamples).toHaveBeenCalledWith(1, [3], "च");
    await userEvent.click(tiles[2]);
    await userEvent.click(screen.getByRole("button", { name: "Not a mix-up (1)" }));
    expect(api.confirmSamples).toHaveBeenCalledWith(1, [3]);
    expect(refresh).toHaveBeenCalled();
  });

  it("marks the letters made by the system, selects them, and makes variants of a small group", async () => {
    vi.mocked(api.groupSamples).mockResolvedValue({ total: 3, offset: 0, samples: [
      sample(1), sample(2, { source: "generated", page_id: null, rules: "generated: a varied copy of #1" }), sample(3)] });
    vi.mocked(api.variants).mockResolvedValue({ ...ok, made: 4, built: 1 });
    const { act } = renderView((ctx) => (
      <GroupView group={group({ samples: 3, generated: 1, label_dev: "घो", label_guj: "ઘો", status: "labelled" })} ctx={ctx} />
    ));
    const tiles = await findTiles();
    expect(within(tiles[1]).getByLabelText("system generated")).toBeInTheDocument();
    expect(within(tiles[0]).queryByLabelText("system generated")).toBeNull();
    expect(tiles[1]).toHaveAttribute("title", expect.stringContaining("system generated (a varied copy of #1)"));
    expect(screen.getByText(/2 real, 1 system generated/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Select generated (1)" }));
    expect(tiles[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("button", { name: "Make variants" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("goes back to not reviewed");           // it was reviewed
    await userEvent.click(within(dialog).getByRole("button", { name: "Make variants" }));
    expect(api.variants).toHaveBeenCalledWith(1, 5);
    expect(act).toHaveBeenCalled();
    expect(await screen.findByText(/4 letters made \(1 built from parts\)/)).toBeInTheDocument();
  });

  it("makes no variants without a label, a real letter, or room", async () => {
    for (const g of [group({ label_dev: "" }), group({ label_dev: "क", samples: 6, generated: 6 }),
                     group({ label_dev: "क", samples: 10 })]) {
      const { unmount } = renderView((ctx) => <GroupView group={g} ctx={ctx} />);
      await findTiles();
      expect(screen.getByRole("button", { name: "Make variants" })).toBeDisabled();
      unmount();
    }
  });

  it("moves through the samples with the arrow keys; Shift extends the selection, also in a locked group", async () => {
    renderView((ctx) => <GroupView group={group({ locked: true })} ctx={ctx} />);
    const tiles = await findTiles();
    const user = userEvent.setup();
    await user.keyboard("{ArrowRight}");                 // nothing selected: the first sample
    expect(tiles[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");   // stops at the last
    expect(tiles[2]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    expect(tiles[1]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(tiles[0]).toHaveAttribute("aria-selected", "true");
  });

  it("moves the selected samples to Unsure", async () => {
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    const tiles = await findTiles();
    const user = userEvent.setup();
    await user.click(tiles[0]);
    await user.keyboard("{Shift>}");
    await user.click(tiles[2]);                        // shift-click: the range 1..3
    await user.keyboard("{/Shift}");
    expect(screen.getByText("3 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "To Unsure" }));
    expect(api.move).toHaveBeenCalledWith(1, expect.arrayContaining([1, 2, 3]), null);
  });

  it("shows the page on hover and opens the sample on its page with a double-click", async () => {
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    const tile = (await findTiles())[1];
    expect(tile.getAttribute("title")).toMatch(/^p1\.png · line 1, letter 2/);
    await userEvent.dblClick(tile);
    expect(window.location.hash).toBe("#/books/1/pages/1/2");
  });

  it("shows one selected letter on its line, and opens it from there", async () => {
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    const tiles = await findTiles();
    expect(screen.queryByLabelText("The letter on its line")).toBeNull();
    await userEvent.click(tiles[1]);
    const line = screen.getByLabelText("The letter on its line");
    expect(within(line).getByRole("img").getAttribute("src")).toBe("/ctx/2.png?token=t&v=0");
    expect(line).toHaveTextContent("p1.png · line 1");
    const user = userEvent.setup();
    await user.keyboard("{Control>}");
    await user.click(tiles[2]);                                       // two selected: no line
    await user.keyboard("{/Control}");
    expect(screen.queryByLabelText("The letter on its line")).toBeNull();
    await userEvent.click(tiles[1]);
    await userEvent.click(screen.getByRole("button", { name: "Open on its page" }));
    expect(window.location.hash).toBe("#/books/1/pages/1/2");
  });

  it("comes back to the letter from its page: selected and outlined, or its neighbour if it has left", async () => {
    window.location.hash = "#/books/1/review/5";
    const view = renderView((ctx) => <GroupView group={group({ label_guj: "ને", code: "g0005" })} ctx={ctx} />);
    await userEvent.dblClick((await findTiles())[1]);
    expect(window.location.hash).toBe("#/books/1/pages/1/2");
    expect(backTo(1)?.label).toBe("ને (g0005)");
    expect(backTo(2)).toBeNull();                                      // another book
    view.unmount();
    goBack();
    expect(window.location.hash).toBe("#/books/1/review/5");
    expect(backTo(1)).toBeNull();
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    await waitFor(() => expect(screen.getByText("1 selected")).toBeInTheDocument());
    const tiles = await findTiles();
    expect(tiles[1]).toHaveClass("marked");
    expect(tiles[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.click(tiles[0]);
    expect(tiles[1]).not.toHaveClass("marked");
  });

  it("marks the next letter when the one opened has left the group", async () => {
    window.location.hash = "#/books/1/review/5";
    const view = renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    await userEvent.dblClick((await findTiles())[1]);
    view.unmount();
    vi.mocked(api.groupSamples).mockResolvedValue({ total: 2, offset: 0, samples: [sample(1), sample(3)] });
    goBack();
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    expect(await screen.findByText(/no longer here .*marks the letter after it/)).toBeInTheDocument();
    expect((await findTiles())[1]).toHaveClass("marked");             // sample 3
    expect(screen.getByText("Click samples to select them")).toBeInTheDocument();
  });

  it("makes a new group with the N key and opens it", async () => {
    vi.mocked(api.newGroup).mockResolvedValue({ ...ok, group_id: 9 });
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    await userEvent.click((await findTiles())[1]);
    await userEvent.keyboard("n");
    expect(api.newGroup).toHaveBeenCalledWith(1, [2]);
    await waitFor(() => expect(window.location.hash).toBe("#/books/1/review/9"));
  });

  it("deletes the selection with the Delete key", async () => {
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />);
    await userEvent.click((await findTiles())[0]);
    await userEvent.keyboard("{Delete}");
    expect(api.deleteSamples).toHaveBeenCalledWith(1, [1]);
  });

  it("merges another group into this one", async () => {
    const other = group({ id: 6, code: "g0006", label_guj: "ક" });
    renderView((ctx) => <GroupView group={group()} ctx={ctx} />, [group(), other]);
    await userEvent.click(await screen.findByRole("button", { name: "Merge another group into this one…" }));
    const picker = screen.getByRole("dialog", { name: "Merge a group" });
    expect(picker).toHaveTextContent("Merge a group into g0005");
    expect(within(picker).getByTitle("ખ (ख): no group to merge").tagName).toBe("SPAN");    // nothing to merge
    await userEvent.click(within(within(picker).getByLabelText("Groups without a label")).getByTitle(/^Merge g0006/));
    expect(api.merge).toHaveBeenCalledWith(1, 5, [6]);
    expect(screen.queryByRole("dialog", { name: "Merge a group" })).toBeNull();
  });

  it("marks a group labelled automatically as reviewed", async () => {
    renderView((ctx) => <GroupView group={group({ label_dev: "की", label_guj: "કી", status: "auto" })} ctx={ctx} />);
    const box = await screen.findByRole("checkbox", { name: "Reviewed" });
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    await userEvent.click(box);
    expect(api.status).toHaveBeenCalledWith(1, 5, { reviewed: true });
  });

  it("a locked group can only be unlocked", async () => {
    renderView((ctx) => <GroupView group={group({ locked: true })} ctx={ctx} />);
    await userEvent.click((await findTiles())[0]);
    expect(screen.getByRole("button", { name: "To Unsure" })).toBeDisabled();
    expect(screen.getByLabelText("Label")).toBeDisabled();
    await userEvent.keyboard("u");
    expect(api.move).not.toHaveBeenCalled();
    await userEvent.click(screen.getByLabelText("Locked"));
    expect(api.status).toHaveBeenCalledWith(1, 5, { locked: false });
  });

  it("shows a large group 200 samples at a time", async () => {
    vi.mocked(api.groupSamples).mockImplementation(async (_g, offset = 0, limit = 200) => ({
      total: 2000, offset, samples: Array.from({ length: limit }, (_, i) => sample(offset + i + 1)),
    }));
    renderView((ctx) => <GroupView group={group({ samples: 2000 })} ctx={ctx} />);
    await waitFor(async () => expect(await findTiles()).toHaveLength(200), { timeout: 15000 });
    await userEvent.click(screen.getByRole("button", { name: "Show more (200 of 2000)" }));
    await waitFor(async () => expect(await findTiles()).toHaveLength(400), { timeout: 15000 });
  });
});
