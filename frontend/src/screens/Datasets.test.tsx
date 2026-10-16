import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, AppInfo, BookSummary, Job } from "../api";
import Datasets from "./Datasets";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, api: { datasets: vi.fn(), createDataset: vi.fn(), renameBook: vi.fn(), deleteBook: vi.fn(),
    uploadPage: vi.fn(), copyFolder: vi.fn(), pickFolder: vi.fn(), chooseLibrary: vi.fn(), chooseUploads: vi.fn() } };
});

const dataset: BookSummary = {
  id: 1, name: "Vachanamrut", kind: "dataset", datasets: [], used_by: [], input_dir: "/pages", writing: "handwritten", read_dir: "", read_pdf: "", read_pages: 0, reviewed: 0, reader_id: null,
  pages: 2, samples: 854, groups: 54, labelled: 27, unsure: 236,
  created_at: null, updated_at: "2026-10-04T09:00:00+00:00", captured_at: null,
};
const info: AppInfo = { version: "0.1.0", library: "/lib", mode: "browser", can_pick_folder: false, uploads: "/lib/uploads" };
const made = { ...dataset, id: 7, settings: {}, undo: 0, redo: 0, job: null };
const job = { id: "j1", book_id: 7, kind: "import_pdf", status: "running" } as Job;

describe("Datasets", () => {
  beforeEach(() => {
    vi.mocked(api.datasets).mockResolvedValue([{ ...dataset, used_by: [{ id: 2, name: "Vachanamrut 1933" }] }]);
    vi.mocked(api.createDataset).mockResolvedValue(made);
    vi.mocked(api.uploadPage).mockReset();
    window.location.hash = "";
  });

  it("lists the datasets with their numbers and the books that use them", async () => {
    render(<Datasets info={info} onLibraryChanged={() => {}} />);
    const table = await screen.findByRole("table", { name: "Datasets" });
    expect(within(table).getByText("854")).toBeInTheDocument();
    expect(within(table).getByText("(50%)")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Vachanamrut 1933" }));   // used by
    expect(window.location.hash).toBe("#/books/2");
  });

  it("creates a dataset from an uploaded PDF and opens Pages & capture", async () => {
    vi.mocked(api.uploadPage).mockResolvedValue({ book: null, job });
    render(<Datasets info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "New set");
    await userEvent.upload(screen.getByLabelText("Page images or a PDF"), new File(["%PDF"], "set.pdf", { type: "application/pdf" }));
    expect(screen.getByText("set.pdf")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    expect(api.createDataset).toHaveBeenCalledWith("New set", "handwritten");
    await waitFor(() => expect(window.location.hash).toBe("#/books/7/capture"));
    expect(vi.mocked(api.uploadPage).mock.calls[0][0]).toBe("dataset");
  });

  it("creates a dataset whose folder's images are copied", async () => {
    vi.mocked(api.copyFolder).mockResolvedValue({ ...job, kind: "copy_pages" });
    render(<Datasets info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "Scans");
    await userEvent.click(screen.getByRole("radio", { name: /Copy a folder/ }));
    expect(screen.getByRole("button", { name: "Create dataset" })).toBeDisabled();             // a folder is needed
    await userEvent.type(screen.getByPlaceholderText("/path/to/the/page/images"), "/scans");
    await userEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    expect(api.copyFolder).toHaveBeenCalledWith(7, "/scans");
    await waitFor(() => expect(window.location.hash).toBe("#/books/7/capture"));
    expect(api.uploadPage).not.toHaveBeenCalled();
  });

  it("creates a dataset without pages", async () => {
    render(<Datasets info={info} onLibraryChanged={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/Vachanamrut, part 1/), "Empty");
    await userEvent.click(screen.getByRole("radio", { name: /Later/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    await waitFor(() => expect(window.location.hash).toBe("#/books/7/capture"));
  });

  it("asks before deleting, and says which books learn from it", async () => {
    vi.mocked(api.deleteBook).mockResolvedValue(undefined);
    render(<Datasets info={info} onLibraryChanged={() => {}} />);
    const table = await screen.findByRole("table", { name: "Datasets" });
    await userEvent.click(within(table).getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("dialog")).toHaveTextContent('"Vachanamrut 1933" learn from it');
    expect(screen.getByRole("dialog")).toHaveTextContent("pages in a folder of your own are not touched");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect(api.deleteBook).toHaveBeenCalledWith(1);
  });
});
