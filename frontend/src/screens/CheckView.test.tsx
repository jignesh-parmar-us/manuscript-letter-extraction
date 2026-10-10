import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import CheckView from "./CheckView";
import { renderView, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { checkThese: vi.fn(), labelSamples: vi.fn() } };
});

const item = (id: number) => ({ sample_id: id, group_id: 5, group_code: "g0005", label: "या", read: "था", label_guj: "યા",
  read_guj: "થા", prob: 0.99, reviewed: true, locked: false, sample: sample(id) });

describe("CheckView", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.checkThese).mockResolvedValue([item(1), item(2)]);
    vi.mocked(api.labelSamples).mockResolvedValue({ undo: 1, redo: 0 });
    window.location.hash = "";
  });

  it("moves a letter to the reader's label, hides one that is right, opens its group", async () => {
    renderView((ctx) => <CheckView ctx={ctx} readerId={7} />);
    const list = await screen.findByLabelText("Letters to check");
    expect(within(list).getAllByText(/reads/)).toHaveLength(2);
    await userEvent.click(within(list).getAllByRole("button", { name: "Move to થા" })[0]);
    expect(api.labelSamples).toHaveBeenCalledWith(1, [1], "था");
    await userEvent.click(within(list).getAllByRole("button", { name: "It is right" })[1]);
    expect(screen.getByText("Check these")).toHaveTextContent("(1)");
    expect(JSON.parse(localStorage.getItem("check-right-7")!)).toEqual([2]);
    await userEvent.click(within(list).getByRole("button", { name: "Open group" }));
    expect(window.location.hash).toBe("#/books/1/review/5");
  });

  it("explains when the book has no reader", () => {
    renderView((ctx) => <CheckView ctx={ctx} readerId={null} />);
    expect(screen.getByText(/no letter reader yet/)).toBeInTheDocument();
  });
});
