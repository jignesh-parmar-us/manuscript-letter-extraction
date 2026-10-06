import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import GroupView from "./GroupView";
import { findTiles, group, renderView, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { groupSamples: vi.fn(), move: vi.fn(), newGroup: vi.fn(), deleteSamples: vi.fn(),
    merge: vi.fn(), dissolve: vi.fn(), status: vi.fn(), label: vi.fn(), checkLabel: vi.fn() } };
});
const ok = { undo: 1, redo: 0 };

describe("GroupView", () => {
  beforeEach(() => {
    window.location.hash = "";
    vi.mocked(api.groupSamples).mockResolvedValue({ total: 3, offset: 0, samples: [sample(1), sample(2), sample(3)] });
    for (const f of [api.move, api.deleteSamples, api.merge, api.status, api.label]) vi.mocked(f).mockResolvedValue(ok);
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
