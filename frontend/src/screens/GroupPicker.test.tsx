import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import GroupPicker from "./GroupPicker";
import { group } from "./reviewTestUtils";

const iso = (min: number) => `2026-10-06T10:${String(min).padStart(2, "0")}:00+00:00`;
const unlabelled = Array.from({ length: 35 }, (_, i) =>
  group({ id: 100 + i, code: `g${String(100 + i).padStart(4, "0")}`, samples: 3, updated_at: iso(i) }));
const groups = [
  group({ id: 1, code: "g0001", label_dev: "क", label_guj: "ક", samples: 40 }),
  group({ id: 2, code: "g0002", label_dev: "रहे", label_guj: "રહે", samples: 8 }),
  ...unlabelled,
];

describe("GroupPicker", () => {
  it("picks a letter's group, a new label, another labelled group, or an unlabelled one", async () => {
    const onPick = vi.fn();
    render(<GroupPicker groups={groups} count={2} onPick={onPick} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "Move to" });
    expect(dialog).toHaveTextContent("Move the 2 letters to…");
    await userEvent.click(within(dialog).getByTitle(/^Move into ક \(g0001/));
    expect(onPick).toHaveBeenLastCalledWith({ groupId: 1, name: "ક (g0001)" });
    await userEvent.click(within(dialog).getByTitle("Put them in a new group labelled ખ (ख)"));
    expect(onPick).toHaveBeenLastCalledWith({ label: "ख" });
    await userEvent.click(within(within(dialog).getByLabelText("Other labelled groups")).getByRole("button"));
    expect(onPick).toHaveBeenLastCalledWith({ groupId: 2, name: "રહે (g0002)" });
  });

  it("lists unlabelled groups newest first, 30 at a time", async () => {
    render(<GroupPicker groups={groups} count={1} onPick={() => {}} onClose={() => {}} />);
    const list = screen.getByLabelText("Groups without a label");
    const codes = () => within(list).getAllByRole("button").map((b) => b.textContent!.slice(0, 5));
    expect(codes().length).toBe(30);
    expect(codes()[0]).toBe("g0134");                                       // the newest
    await userEvent.click(screen.getByRole("button", { name: "Show more (5 left)" }));
    expect(codes().length).toBe(35);
    expect(screen.queryByRole("button", { name: /Show more/ })).toBeNull();
  });

  it("does not offer the current group, and closes with Escape", async () => {
    const onClose = vi.fn();
    render(<GroupPicker groups={groups} count={1} currentGroupId={1} onPick={() => {}} onClose={onClose} />);
    expect(screen.getByTitle("ક: this group").tagName).toBe("SPAN");                   // not a button
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("in merge mode, picks only letters with a group, including an unlabelled group suggested as the letter", async () => {
    const onPick = vi.fn();
    const sug = { label_dev: "ख", label_guj: "ખ", share: 0.9, count: 9, read: 10, engine: "tesseract" as const, merge_into: null };
    const gs = [...groups, group({ id: 50, code: "g0050", samples: 12, suggestion: sug })];
    render(<GroupPicker mode="merge" into="ક (g0001)" groups={gs} count={0} currentGroupId={1} onPick={onPick} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: "Merge a group" });
    expect(dialog).toHaveTextContent("Merge a group into ક (g0001)");
    expect(within(dialog).getByTitle("ગ (ग): no group to merge").tagName).toBe("SPAN");
    await userEvent.click(within(dialog).getByTitle(/^Merge ખ \(g0050/));                 // amber: suggested as ख
    expect(onPick).toHaveBeenLastCalledWith({ groupId: 50, name: "ખ (g0050)" });
  });
});
