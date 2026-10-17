import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { droppedFiles, PageFilePicker } from "./UploadPages";

const file = (name: string) => new File(["x"], name);

/** A drop's data: the files, and (as Chrome and Safari give it) an entry per item that says if it is a folder. */
const drop = (files: File[], folder = false) => ({
  dataTransfer: {
    types: ["Files"],
    files,
    items: files.map(() => ({ kind: "file", webkitGetAsEntry: () => ({ isDirectory: folder }) })),
  },
});

describe("PageFilePicker (C25: drop files)", () => {
  it("takes dropped page images", () => {
    const onChange = vi.fn();
    render(<PageFilePicker files={[]} onChange={onChange} />);
    const zone = screen.getByText("Page images or a PDF").closest("label")!;
    fireEvent.dragOver(zone, drop([]));
    expect(zone).toHaveClass("over");
    const files = [file("p1.jpg"), file("p2.jpg")];
    fireEvent.drop(zone, drop(files));
    expect(onChange).toHaveBeenCalledWith(files);
    expect(zone).not.toHaveClass("over");
  });

  it("checks dropped files like chosen ones", () => {
    render(<PageFilePicker files={[file("a.pdf"), file("b.jpg")]} onChange={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("page images or one PDF, not both");
  });

  it("refuses a dropped folder", () => {
    const onChange = vi.fn();
    render(<PageFilePicker files={[]} onChange={onChange} />);
    fireEvent.drop(screen.getByText("Page images or a PDF").closest("label")!, drop([file("scans")], true));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Drop the page images, not their folder.");
  });

  it("ignores a drop while disabled, and drags that carry no files", () => {
    const onChange = vi.fn();
    const { rerender } = render(<PageFilePicker files={[]} onChange={onChange} disabled />);
    const zone = () => screen.getByText("Page images or a PDF").closest("label")!;
    fireEvent.drop(zone(), drop([file("p1.jpg")]));
    rerender(<PageFilePicker files={[]} onChange={onChange} />);
    fireEvent.drop(zone(), { dataTransfer: { types: ["text/plain"], files: [], items: [] } });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("droppedFiles", () => {
  it("gives the files, null for a folder, nothing without data", () => {
    const f = [file("p.png")];
    expect(droppedFiles(drop(f).dataTransfer as unknown as DataTransfer)).toEqual(f);
    expect(droppedFiles(drop(f, true).dataTransfer as unknown as DataTransfer)).toBeNull();
    expect(droppedFiles(null)).toEqual([]);
  });
});
