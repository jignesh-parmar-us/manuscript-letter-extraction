import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PageInfo } from "../api";
import PagePicker from "./PagePicker";

const page = (id: number, file: string, samples = 600): PageInfo => ({
  id, file, width: 1000, height: 1400, status: "OK", message: "", lines: 12, samples, image: "",
});
const pages = [page(1, "Untitled-15.jpg"), page(2, "Untitled-16.jpg"), page(3, "Untitled-41.jpg", 689), page(4, "cover.png", 0)];

describe("PagePicker", () => {
  it("lists every page with its letters, marks the open one, and picks one", async () => {
    const onPick = vi.fn();
    render(<PagePicker pages={pages} currentId={2} onPick={onPick} onClose={() => {}} />);
    const list = screen.getByRole("listbox", { name: "Pages" });
    expect(within(list).getAllByRole("option").length).toBe(4);
    expect(within(list).getByRole("option", { selected: true })).toHaveTextContent("Untitled-16.jpg");
    await userEvent.click(within(list).getByRole("option", { name: /Untitled-41\.jpg.*689 letters/ }));
    expect(onPick).toHaveBeenCalledWith(pages[2]);
  });

  it("searches by name; Enter opens the first match, Esc closes", async () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(<PagePicker pages={pages} currentId={null} onPick={onPick} onClose={onClose} />);
    const search = screen.getByRole("textbox", { name: "Search pages" });
    expect(search).toHaveFocus();
    await userEvent.type(search, "41");
    expect(within(screen.getByRole("listbox", { name: "Pages" })).getAllByRole("option").length).toBe(1);
    await userEvent.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalledWith(pages[2]);
    await userEvent.clear(search);
    await userEvent.type(search, "nothing");
    expect(screen.getByText(/No page matches/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
