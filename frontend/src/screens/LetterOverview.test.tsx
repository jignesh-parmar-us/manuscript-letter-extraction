import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import LetterOverview, { CONSONANTS, missingCount, otherLabelled, SIGNS, VOWELS } from "./LetterOverview";
import { group, renderView } from "./reviewTestUtils";

const sug = (label_dev: string) => ({ label_dev, label_guj: "", share: 0.9, count: 9, read: 10, engine: "tesseract" as const,
  merge_into: null });
const groups = [
  group({ id: 1, code: "g0001", label_dev: "क", label_guj: "ક", samples: 40 }),
  group({ id: 2, code: "g0002", label_dev: "कि", label_guj: "કિ", samples: 12 }),
  group({ id: 3, code: "g0003", samples: 9, suggestion: sug("ने") }),
  group({ id: 4, code: "g0004", label_dev: "अ", label_guj: "અ", samples: 7 }),
  group({ id: 5, code: "g0005", label_dev: "रहे", label_guj: "રહે", samples: 8 }),
  group({ id: 6, code: "g0006", label_dev: "क्ष", label_guj: "ક્ષ", samples: 5 }),
  group({ id: 7, code: "g0007", label_dev: "कं", label_guj: "કં", samples: 4 }),
];

describe("LetterOverview", () => {
  it("counts the letters without a labelled group", () => {
    const total = VOWELS.length + CONSONANTS.length * SIGNS.length;
    expect(missingCount(groups)).toBe(total - 3);                     // क, कि and अ have groups
  });

  it("shows labelled, suggested and missing letters, and opens their groups", async () => {
    window.location.hash = "";
    renderView((ctx) => <LetterOverview ctx={ctx} />, groups);
    const table = screen.getByRole("table", { name: "Letters and their groups" });
    expect(within(table).getByTitle(/^ક \(क\): 40 letters in g0001/).closest("td")).toHaveClass("cell-have");
    const ne = within(table).getByTitle(/^ને \(ने\): no labelled group; g0003/);
    expect(ne.closest("td")).toHaveClass("cell-suggested");
    expect(within(table).getByTitle(/^ખ \(ख\): no group yet/).closest("td")).toHaveClass("cell-missing");
    await userEvent.click(ne);
    expect(window.location.hash).toBe("#/books/1/review/3");
  });

  it("lists the labelled groups that are not letters of the table", async () => {
    window.location.hash = "";
    expect(otherLabelled(groups, false).map((g) => g.label_dev)).toEqual(["कं", "क्ष", "रहे"]);
    expect(otherLabelled(groups, true).map((g) => g.label_dev)).toEqual(["कं", "रहे"]);   // क्ष is in the table now
    renderView((ctx) => <LetterOverview ctx={ctx} />, groups);
    const others = screen.getByLabelText("Other labelled groups");
    expect(within(others).getAllByRole("button").map((b) => b.textContent)).toEqual(["કં4", "ક્ષ5", "રહે8"]);
    await userEvent.click(within(others).getByTitle(/^રહે/));
    expect(window.location.hash).toBe("#/books/1/review/5");
  });

  it("can add the conjuncts and hide the rows with no group yet", async () => {
    renderView((ctx) => <LetterOverview ctx={ctx} />, groups);
    const table = () => screen.getByRole("table", { name: "Letters and their groups" });
    expect(within(table()).queryByTitle(/^ક્ષ \(क्ष\)/)).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: /Include the conjuncts/ }));
    expect(within(table()).getByTitle(/^ક્ષ \(क्ष\): 5 letters/)).toBeInTheDocument();
    const rowsBefore = within(table()).getAllByRole("row").length;
    await userEvent.click(screen.getByRole("checkbox", { name: /Hide rows with no group yet/ }));
    const left = within(table()).getAllByRole("row").map((r) => r.querySelector("th")?.textContent);
    expect(left).toEqual(["", "vowels", "ક", "ન", "ક્ષ"]);                 // header, then rows with something
    expect(rowsBefore).toBeGreaterThan(left.length);
    expect(screen.getByRole("checkbox", { name: /hidden\)/ })).toBeChecked();
  });
});
