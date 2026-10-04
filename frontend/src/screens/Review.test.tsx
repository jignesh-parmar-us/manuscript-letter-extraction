import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book } from "../api";
import Review, { filterGroups, sortGroups } from "./Review";
import { group } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { groups: vi.fn(), undo: vi.fn(), redo: vi.fn() } };
});

const book: Book = {
  id: 1, name: "B", input_dir: "/p", writing: "handwritten",
  pages: 2, samples: 10, groups: 3, labelled: 1, unsure: 4, created_at: null,
  updated_at: null, captured_at: null, settings: {}, undo: 2, redo: 0, job: null,
};
const groups = [
  group({ id: 1, code: "g0001", samples: 9, spread: 0.2, label_dev: "क", label_guj: "ક", status: "labelled" }),
  group({ id: 2, code: "g0002", samples: 4, spread: 0.5 }),
  group({ id: 3, code: "g0003", samples: 0, spread: null }),
];

describe("Review", () => {
  beforeEach(() => {
    vi.mocked(api.groups).mockResolvedValue(groups);
    vi.mocked(api.undo).mockResolvedValue({ undo: 1, redo: 1 });
  });

  it("lists the groups and undoes with Ctrl/Cmd+Z", async () => {
    const onChanged = vi.fn();
    render(<Review book={book} view={undefined} onChanged={onChanged} />);
    expect(await screen.findByText("ક")).toBeInTheDocument();
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(api.undo).toHaveBeenCalledWith(1);
    await waitFor(() => expect(screen.getByRole("button", { name: /Redo/ })).toBeEnabled());
    expect(onChanged).toHaveBeenCalled();
  });

  it("filters and sorts groups", () => {
    expect(filterGroups(groups, "all").map((g) => g.id)).toEqual([1, 2]);
    expect(filterGroups(groups, "empty").map((g) => g.id)).toEqual([3]);
    expect(filterGroups(groups, "unlabelled").map((g) => g.id)).toEqual([2]);
    expect(filterGroups(groups, "mixed").map((g) => g.id)).toEqual([2]);
    expect(sortGroups(groups, "size").map((g) => g.id)).toEqual([1, 2, 3]);
    expect(sortGroups(groups, "spread").map((g) => g.id)).toEqual([2, 1, 3]);
    const labelled = [
      group({ id: 1, code: "g0001", label_dev: "ख" }),
      group({ id: 2, code: "g0002" }),
      group({ id: 3, code: "g0003", label_dev: "अ" }),
      group({ id: 4, code: "g0004", label_dev: "कि" }),
      group({ id: 5, code: "g0005", label_dev: "क" }),
    ];
    expect(sortGroups(labelled, "label").map((g) => g.id)).toEqual([3, 5, 4, 1, 2]);   // अ क कि ख, then unlabelled
  });
});
