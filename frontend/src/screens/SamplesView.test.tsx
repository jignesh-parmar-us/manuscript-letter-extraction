import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import SamplesView from "./SamplesView";
import { findTiles, renderView, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { unsure: vi.fn(), deleted: vi.fn(), move: vi.fn(), newGroup: vi.fn(),
    deleteSamples: vi.fn(), restoreSamples: vi.fn() } };
});
const ok = { undo: 1, redo: 0 };
const sug = (gid: number) => ({ group_id: gid, code: `g000${gid}`, label_dev: "क", label_guj: "ક", distance: 0.4 });

describe("SamplesView", () => {
  beforeEach(() => {
    vi.mocked(api.unsure).mockResolvedValue({ total: 3, offset: 0, samples: [
      sample(1, { group_id: null, suggestion: sug(5) }), sample(2, { group_id: null, suggestion: sug(6) }),
      sample(3, { group_id: null, suggestion: null })] });
    vi.mocked(api.move).mockResolvedValue(ok);
    vi.mocked(api.restoreSamples).mockResolvedValue(ok);
  });

  it("accepts one suggestion with a click", async () => {
    renderView((ctx) => <SamplesView kind="unsure" ctx={ctx} />);
    await userEvent.click((await screen.findAllByTitle(/Suggested: g0005/))[0]);
    expect(api.move).toHaveBeenCalledWith(1, [1], 5);
  });

  it("accepts the suggestions of the selected samples, one move per group", async () => {
    renderView((ctx) => <SamplesView kind="unsure" ctx={ctx} />);
    await userEvent.keyboard("{Control>}a{/Control}");
    await userEvent.click(screen.getByRole("button", { name: "Accept suggestions (2)" }));
    expect(api.move).toHaveBeenCalledWith(1, [1], 5);
    expect(api.move).toHaveBeenCalledWith(1, [2], 6);
    expect(api.move).toHaveBeenCalledTimes(2);
  });

  it("restores deleted samples", async () => {
    vi.mocked(api.deleted).mockResolvedValue({ total: 1, offset: 0, samples: [sample(7, { deleted: true, group_id: null })] });
    renderView((ctx) => <SamplesView kind="deleted" ctx={ctx} />);
    await userEvent.click((await findTiles())[0]);
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(api.restoreSamples).toHaveBeenCalledWith(1, [7]);
  });
});
