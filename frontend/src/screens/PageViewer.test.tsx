import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, Book, PageDetail } from "../api";
import PageViewer, { groupColour } from "./PageViewer";
import { group, sample } from "./reviewTestUtils";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { pages: vi.fn(), page: vi.fn(), groups: vi.fn(), crop: vi.fn(), join: vi.fn(), split: vi.fn(),
    upload: vi.fn(), deleteSamples: vi.fn(), undo: vi.fn(), redo: vi.fn(), move: vi.fn(), newGroup: vi.fn(), label: vi.fn(),
    checkLabel: vi.fn(), labelSamples: vi.fn() } };
});

const book = { id: 1 } as Book;
const page: PageDetail = {
  id: 3, book_id: 1, file: "p1.png", width: 1000, height: 500, status: "OK", message: "", line_spacing: 110,
  image: "/files/pages/3", lines: [],
  samples: [
    sample(1, { box: [100, 50, 40, 60], group_id: 5 }),
    sample(2, { box: [150, 50, 40, 60], group_id: null }),
    sample(3, { box: [200, 50, 40, 60], group_id: 5 }),
  ],
};
const ok = { undo: 1, redo: 0 };

/** The overlay is drawn at half size: 500 x 250 screen pixels for the 1000 x 500 page. */
function halfSize() {
  const svg = screen.getByLabelText("Samples on the page");
  svg.getBoundingClientRect = () => ({ left: 10, top: 20, width: 500, height: 250 }) as DOMRect;
}

describe("PageViewer", () => {
  beforeEach(() => {
    vi.mocked(api.pages).mockResolvedValue([{ id: 3, file: "p1.png", width: 1000, height: 500, status: "OK", message: "",
      lines: 1, samples: 3, image: "" }]);
    vi.mocked(api.page).mockResolvedValue(page);
    vi.mocked(api.groups).mockResolvedValue([]);
    vi.mocked(api.deleteSamples).mockResolvedValue(ok);
  });

  it("draws a box for every sample, unsure ones dashed", async () => {
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    expect(await screen.findByTestId("box-1")).toBeInTheDocument();
    expect(screen.getByTestId("box-2")).toHaveClass("unsure");
    expect(screen.getByTestId("box-1")).toHaveAttribute("stroke", groupColour(5));
  });

  it("keeps the box layer the size of the image at every zoom", async () => {
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    await screen.findByTestId("box-1");
    for (const zoom of ["0.25", "0.5", "0.75", "1"]) {
      await userEvent.selectOptions(screen.getByLabelText("Zoom"), zoom);
      const img = screen.getByAltText("p1.png");
      const frame = img.parentElement as HTMLElement;     // the box layer fills this frame
      const z = Number(zoom);
      expect(img).toHaveAttribute("width", String(1000 * z));
      expect(img).toHaveAttribute("height", String(500 * z));
      expect(frame.style.width).toBe(`${1000 * z}px`);
      expect(frame.style.height).toBe(`${500 * z}px`);
    }
    expect(screen.getByLabelText("Samples on the page")).toHaveAttribute("viewBox", "0 0 1000 500");
  });

  it("selects the sample named in the address and scrolls it into view", async () => {
    const scrollTo = vi.fn();
    HTMLElement.prototype.scrollTo = scrollTo;
    render(<PageViewer book={book} pageId={3} sampleId={3} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("box-3")).toHaveClass("selected"));
    expect(screen.getByTestId("box-1")).not.toHaveClass("selected");
    expect(scrollTo).toHaveBeenCalledWith({ left: 110, top: 40 });   // centre (220, 80) at 50%, view 0 x 0
    const ring = screen.getByTestId("focus-ring");                    // around box 3: 200,50 40x60, pad 21
    expect([ring.getAttribute("x"), ring.getAttribute("y"), ring.getAttribute("width")]).toEqual(["179", "29", "82"]);
    fireEvent.click(screen.getByTestId("box-1"));
    expect(screen.queryByTestId("focus-ring")).not.toBeInTheDocument();
  });

  it("puts the selected samples in a group without leaving the page", async () => {
    vi.mocked(api.groups).mockResolvedValue([
      group({ id: 5, code: "g0005", samples: 2 }),
      group({ id: 6, code: "g0006", label_dev: "क", label_guj: "ક", samples: 9 }),
      group({ id: 7, code: "g0007", locked: true, samples: 4 }),
    ]);
    vi.mocked(api.move).mockResolvedValue(ok);
    vi.mocked(api.newGroup).mockResolvedValue({ ...ok, group_id: 8 });
    vi.mocked(api.labelSamples).mockResolvedValue({ ...ok, group_id: 9 });
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("box-2"));              // an unsure sample
    expect(screen.getByRole("button", { name: "To Unsure" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Move to…" }));
    let picker = screen.getByRole("dialog", { name: "Move to" });
    await userEvent.click(within(picker).getByTitle(/^Move into ક \(g0006/));          // a letter with a group
    expect(api.move).toHaveBeenCalledWith(1, [2], 6);
    expect(await screen.findByText(/moved to ક/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Move to" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Move to…" }));
    picker = screen.getByRole("dialog", { name: "Move to" });
    const unlabelled = within(picker).getByLabelText("Groups without a label");
    expect(within(unlabelled).getByTitle(/^Move into g0007/)).toBeDisabled();            // locked
    await userEvent.click(within(picker).getByTitle("Put them in a new group labelled ખ (ख)")); // no group yet
    expect(api.labelSamples).toHaveBeenCalledWith(1, [2], "ख");
    fireEvent.click(screen.getByTestId("box-1"), { shiftKey: true });
    await userEvent.click(screen.getByRole("button", { name: "New group" }));
    expect(api.newGroup).toHaveBeenCalledWith(1, [2, 1]);
    await userEvent.click(screen.getByRole("button", { name: "To Unsure" }));
    expect(api.move).toHaveBeenLastCalledWith(1, [2, 1], null);
  });

  it("moves between pages with the page chooser and the arrows", async () => {
    vi.mocked(api.pages).mockResolvedValue([
      { id: 2, file: "p0.png", width: 1000, height: 500, status: "OK", message: "", lines: 1, samples: 5, image: "" },
      { id: 3, file: "p1.png", width: 1000, height: 500, status: "OK", message: "", lines: 1, samples: 3, image: "" },
      { id: 4, file: "p2.png", width: 1000, height: 500, status: "OK", message: "", lines: 1, samples: 7, image: "" },
    ]);
    window.location.hash = "";
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    const choose = await screen.findByRole("button", { name: /p1.png 2 of 3/ });
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(window.location.hash).toBe("#/books/1/pages/4");
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(window.location.hash).toBe("#/books/1/pages/2");
    await userEvent.click(choose);
    const dialog = screen.getByRole("dialog", { name: "Choose a page" });
    await userEvent.click(within(dialog).getByRole("option", { name: /p2.png/ }));
    expect(window.location.hash).toBe("#/books/1/pages/4");
    expect(screen.queryByRole("dialog", { name: "Choose a page" })).toBeNull();
  });

  it("keeps the selection below the page, and marks the spot of the last change", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("box-1"));
    const dock = screen.getByLabelText("Selection");
    const pageArea = screen.getByLabelText("Samples on the page");
    expect(pageArea.compareDocumentPosition(dock) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();  // below the page
    fireEvent.click(screen.getByTestId("box-3"), { shiftKey: true });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(api.deleteSamples).toHaveBeenCalledWith(1, [1, 3]);
    const spot = await screen.findByTestId("last-spot");                    // around both deleted boxes
    expect([spot.getAttribute("x"), spot.getAttribute("width")]).toEqual(["92", "156"]);
    fireEvent.click(screen.getByTestId("box-2"));                          // the next click clears it
    expect(screen.queryByTestId("last-spot")).toBeNull();
  });

  it("labels the selected samples: into the group with that label, or a new labelled group", async () => {
    vi.mocked(api.groups).mockResolvedValue([
      group({ id: 6, code: "g0006", label_dev: "क", label_guj: "ક", samples: 9 }),
      group({ id: 7, code: "g0007", label_dev: "ख", label_guj: "ખ", locked: true, samples: 4 }),
    ]);
    vi.mocked(api.checkLabel).mockImplementation(async (text) =>
      text === "ક"
        ? { ok: true, devanagari: "क", gujarati: "ક", used_by: [{ id: 6, code: "g0006", locked: false, samples: 9 }] }
        : { ok: true, devanagari: "ग", gujarati: "ગ", used_by: [] });
    vi.mocked(api.move).mockResolvedValue(ok);
    vi.mocked(api.newGroup).mockResolvedValue({ ...ok, group_id: 8 });
    vi.mocked(api.label).mockResolvedValue(ok);
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("box-2"));
    const input = screen.getByLabelText("Label");
    await userEvent.type(input, "ક");
    const labelIt = screen.getByRole("button", { name: "Label it" });
    await waitFor(() => expect(labelIt).toBeEnabled());
    await userEvent.click(labelIt);
    expect(api.move).toHaveBeenCalledWith(1, [2], 6);                   // the existing ક group
    expect(api.newGroup).not.toHaveBeenCalled();
    await userEvent.clear(input);
    await userEvent.type(input, "ગ");                                   // no group has it yet
    await waitFor(() => expect(labelIt).toBeEnabled());
    await userEvent.click(labelIt);
    await waitFor(() => expect(api.label).toHaveBeenCalledWith(1, 8, "ગ"));
    expect(api.newGroup).toHaveBeenCalledWith(1, [2]);
    expect(await screen.findByText(/new group labelled ગ/)).toBeInTheDocument();
  });

  it("joins the selected samples", async () => {
    vi.mocked(api.join).mockResolvedValue({ ...ok, sample: { id: 9, page_id: 3, box: [], source: "joined" } });
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("box-1"));
    fireEvent.click(screen.getByTestId("box-2"), { shiftKey: true });
    await userEvent.click(screen.getByRole("button", { name: "Join (2)" }));
    expect(api.join).toHaveBeenCalledWith(1, [1, 2]);
  });

  it("draws a box on the page and makes a sample from it, in page coordinates", async () => {
    vi.mocked(api.crop).mockResolvedValue({ ...ok, sample: { id: 9, page_id: 3, box: [], source: "cropped" }, overlapping: [2] });
    const onChanged = vi.fn();
    render(<PageViewer book={book} pageId={3} onChanged={onChanged} />);
    await screen.findByTestId("box-1");
    halfSize();
    await userEvent.click(screen.getByRole("button", { name: "Draw a box" }));
    const svg = screen.getByLabelText("Samples on the page");
    fireEvent.mouseDown(svg, { clientX: 60, clientY: 40 });   // page (100, 40)
    fireEvent.mouseMove(svg, { clientX: 85, clientY: 75 });
    fireEvent.mouseUp(svg, { clientX: 85, clientY: 75 });     // page (150, 110)
    await waitFor(() => expect(api.crop).toHaveBeenCalledWith(1, 3, [100, 40, 50, 70]));
    expect(onChanged).toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Delete them" }));
    expect(api.deleteSamples).toHaveBeenCalledWith(1, [2]);
  });

  it("splits the selected sample where it is clicked", async () => {
    vi.mocked(api.split).mockResolvedValue({ ...ok, samples: [{ id: 10 }, { id: 11 }] });
    render(<PageViewer book={book} pageId={3} onChanged={() => {}} />);
    fireEvent.click(await screen.findByTestId("box-3"));
    halfSize();
    await userEvent.click(screen.getByRole("button", { name: "Split" }));
    fireEvent.click(screen.getByTestId("box-3"), { clientX: 120, clientY: 60 });   // page x = 220
    await waitFor(() => expect(api.split).toHaveBeenCalledWith(1, 3, 220));
  });

  it("uploads a letter image as base64", async () => {
    vi.mocked(api.upload).mockResolvedValue({ ...ok, sample: { id: 12, page_id: null, box: [], source: "uploaded" } });
    const { container } = render(<PageViewer book={book} pageId={null} onChanged={() => {}} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File([new Uint8Array([1, 2, 3])], "letter.png", { type: "image/png" }));
    await waitFor(() => expect(api.upload).toHaveBeenCalledWith(1, "letter.png", "AQID"));
  });
});
