import { DndContext } from "@dnd-kit/core";
import { render } from "@testing-library/react";
import { ReactElement, useState } from "react";
import { vi } from "vitest";
import { ActionResult, Group, Sample } from "../api";
import { emptySelection, Selection } from "../components/selection";
import { ReviewContext, useDragSensors } from "./Review";

export const group = (over: Partial<Group> = {}): Group => ({
  id: 5, code: "g0005", kind: "letter", label_dev: "", label_guj: "", status: "auto", locked: false, samples: 3,
  red: 1, black: 2, spread: 0.3, example_id: 1, example_image: null, updated_at: null, suggestion: null, readings: [],
  read: 0, ...over,
});

export const sample = (id: number, over: Partial<Sample> = {}): Sample => ({
  id, page_id: 1, page_file: "p1.png", line: 1, pos: id, box: [0, 0, 10, 10], ink: "black", kind: "letter", source: "auto",
  group_id: 5, distance: 0.1, deleted: false, rules: "", image: `/img/${id}.png`,
  context: `/ctx/${id}.png?token=t`, ...over,
});

/** Renders a review view with a real selection state and a mocked `act`. */
export function renderView(make: (ctx: ReviewContext) => ReactElement, groups: Group[] = [group()]) {
  const act = vi.fn(async (run: () => Promise<ActionResult>) => run());
  function Host() {
    const [selection, setSelection] = useState<Selection>(emptySelection);
    const ctx: ReviewContext = { bookId: 1, version: 0, groups, selection, setSelection, act };
    return <DndContext sensors={useDragSensors()}>{make(ctx)}</DndContext>;
  }
  return { ...render(<Host />), act };
}

/** The sample tiles of the grid (not the options of the dropdowns). */
export async function findTiles() {
  const { screen, within } = await import("@testing-library/react");
  return within(await screen.findByRole("listbox", { name: "Samples" })).findAllByRole("option");
}
