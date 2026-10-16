import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, PageEntry } from "../api";
import PageManager from "./PageManager";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pageList: vi.fn(), excludePage: vi.fn(), deletePage: vi.fn(), movePage: vi.fn() } };
});

const entry = (id: number | null, file: string, over: Partial<PageEntry> = {}): PageEntry => ({
  id, file, number: id, excluded: false, prepared: id !== null, status: id ? "OK" : "new", message: "", lines: 10,
  samples: 200, checked: 0, corrections: 0, reviewed: 0, missing: false, thumb: `/thumb/${file}`, ...over });

describe("PageManager", () => {
  beforeEach(() => {
    vi.mocked(api.pageList).mockResolvedValue({ part: "read", folder: "/scans", owned: false, pages: [
      entry(1, "p1.png", { checked: 3 }), entry(2, "p2.png", { excluded: true }), entry(3, "p3.png"), entry(null, "p4.png"),
    ] });
  });

  it("lists the pages in order: places of the pages used, excluded ones and new files", async () => {
    render(<PageManager bookId={4} kind="book" onChanged={() => {}} onError={() => {}} />);
    const table = await screen.findByRole("table", { name: "Pages" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["1", "", "2", ""]);
    expect(within(rows[1]).getByText("Excluded")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Include" })).toBeInTheDocument();
    expect(within(rows[3]).getByText("Not prepared yet")).toBeInTheDocument();
    expect(within(rows[3]).queryByRole("button", { name: /Move/ })).not.toBeInTheDocument();
    expect(within(rows[0]).getByText("3 checked")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("button", { name: "Move p1.png up" })).toBeDisabled();
    expect(screen.getByText("3 of 4 used, the others excluded")).toBeInTheDocument();
  });

  it("moves a page and reloads", async () => {
    vi.mocked(api.movePage).mockResolvedValue({ page: 3, number: 2 });
    const onChanged = vi.fn();
    render(<PageManager bookId={4} kind="book" onChanged={onChanged} onError={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Move p3.png up" }));
    expect(api.movePage).toHaveBeenCalledWith(4, 3, -1);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(api.pageList).toHaveBeenCalledTimes(2);
  });

  it("asks before excluding a page with checked lines, then excludes with force", async () => {
    vi.mocked(api.excludePage)
      .mockRejectedValueOnce(new ApiError(409, "Page p1.png has 3 checked lines (Line truth).", "needs_confirmation"))
      .mockResolvedValueOnce({ file: "p1.png", excluded: true });
    render(<PageManager bookId={4} kind="book" onChanged={() => {}} onError={() => {}} />);
    const table = await screen.findByRole("table", { name: "Pages" });
    await userEvent.click(within(table).getAllByRole("button", { name: "Exclude" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("3 checked lines");
    await userEvent.click(within(dialog).getByRole("button", { name: "Exclude" }));
    await waitFor(() => expect(api.excludePage).toHaveBeenLastCalledWith(4, "p1.png", true, true));
  });

  it("says what deleting does to a file of one's own folder, and does nothing when not confirmed", async () => {
    render(<PageManager bookId={4} kind="book" onChanged={() => {}} onError={() => {}} />);
    const table = await screen.findByRole("table", { name: "Pages" });
    await userEvent.click(within(table).getAllByRole("button", { name: "Delete" })[2]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Its image stays in your folder");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.deletePage).not.toHaveBeenCalled();
  });
});
