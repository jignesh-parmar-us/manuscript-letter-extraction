// The one way the screens talk to the backend (app/api.py).
//
// Every request carries the session token that the backend wrote into the page
// (window.__TOKEN__). Image URLs from the backend already contain it.
// A failed request throws ApiError with the backend's message (`detail`) and, for
// "needs confirmation" answers, code = "needs_confirmation" (status 409).

declare global {
  interface Window {
    __TOKEN__?: string;
  }
}

export function token(): string {
  return window.__TOKEN__ ?? new URLSearchParams(window.location.search).get("token") ?? "";
}

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
  get needsConfirmation(): boolean {
    return this.status === 409 && this.code === "needs_confirmation";
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "X-Token": token(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = response.statusText || `Error ${response.status}`;
    let code: string | undefined;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join("; ");
      code = data.code;
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail, code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
export const del = <T>(path: string) => request<T>("DELETE", path);

// ---- types of the backend's answers ---------------------------------------------------------

export interface AppInfo {
  version: string;
  library: string;
  mode: "window" | "browser";
  can_pick_folder: boolean;
}

export interface BookSummary {
  id: number;
  name: string;
  input_dir: string;
  pages: number;
  samples: number;
  groups: number;
  labelled: number;
  unsure: number;
  created_at: string | null;
  updated_at: string | null;
  captured_at: string | null;
}

export interface Book extends BookSummary {
  settings: Record<string, unknown>;
  undo: number;
  redo: number;
  job: Job | null;
}

export interface JobPage {
  file: string;
  status: string;
  message: string;
  seconds: number;
}

export interface Job {
  id: string;
  book_id: number;
  kind: "capture" | "add_pages" | "recut_page";
  status: "running" | "done" | "failed" | "cancelled";
  done: number;
  total: number;
  current: string;
  pages: JobPage[];
  result: Record<string, unknown> | null;
  error: string;
  seconds: number;
}

export interface PageProblem {
  file: string;
  problem: "missing" | "changed" | "new";
}

export interface PageInfo {
  id: number;
  file: string;
  width: number;
  height: number;
  status: string;
  message: string;
  lines: number;
  samples: number;
  image: string;
}

export interface Group {
  id: number;
  code: string;
  kind: "letter" | "danda" | "digit";
  label_dev: string;
  label_guj: string;
  status: "auto" | "reviewed" | "labelled";
  locked: boolean;
  samples: number;
  red: number;
  black: number;
  spread: number | null;
  example_id: number | null;
  example_image: string | null;
  updated_at: string | null;
}

export interface Suggestion {
  group_id: number;
  code: string;
  label_dev: string;
  label_guj: string;
  distance: number;
}

export interface Sample {
  id: number;
  page_id: number | null;
  line: number;
  pos: number;
  box: [number, number, number, number];
  ink: "red" | "black";
  kind: string;
  source: string;
  group_id: number | null;
  distance: number | null;
  deleted: boolean;
  rules: string;
  image: string;
  suggestion?: Suggestion | null;
}

export interface SamplePage {
  total: number;
  offset: number;
  samples: Sample[];
}

/** Every action answers with what it did and the new undo / redo counts. */
export interface ActionResult {
  kind?: string;
  group_id?: number;
  undo: number;
  redo: number;
  [key: string]: unknown;
}

export interface LabelInfo {
  ok: boolean;
  error?: string;
  devanagari?: string;
  gujarati?: string;
  code_points_devanagari?: string;
  code_points_gujarati?: string;
  category?: string;
  kept_in_devanagari?: string[];
}

export interface HistoryItem {
  id: number;
  kind: string;
  undone: boolean;
  created_at: string;
  [key: string]: unknown;
}

export interface LineInfo {
  id: number;
  number: number;
  box: [number, number, number, number];
  ink: string;
  image: string;
}

export interface PageDetail {
  id: number;
  book_id: number;
  file: string;
  width: number;
  height: number;
  status: string;
  message: string;
  line_spacing: number;
  image: string;
  lines: LineInfo[];
  samples: Sample[];
}

export interface NewSampleResult extends ActionResult {
  sample?: { id: number; page_id: number | null; box: number[]; source: string };
  samples?: { id: number }[];
  overlapping?: number[];
}

// ---- calls ----------------------------------------------------------------------------------

export const api = {
  app: () => get<AppInfo>("/api/app"),
  chooseLibrary: (path: string) => post<{ library: string; restart_needed: boolean }>("/api/app/library", { path }),
  pickFolder: () => post<{ path: string | null }>("/api/app/pick-folder"),

  books: () => get<BookSummary[]>("/api/books"),
  book: (id: number) => get<Book>(`/api/books/${id}`),
  createBook: (name: string, input_dir: string) => post<Book>("/api/books", { name, input_dir }),
  renameBook: (id: number, name: string) => patch<Book>(`/api/books/${id}`, { name }),
  deleteBook: (id: number) => del<void>(`/api/books/${id}`),
  setSettings: (id: number, settings: Record<string, unknown> | null) =>
    patch<Book>(`/api/books/${id}/settings`, { settings }),
  pageProblems: (id: number) => get<PageProblem[]>(`/api/books/${id}/page-problems`),
  pages: (id: number) => get<PageInfo[]>(`/api/books/${id}/pages`),

  capture: (id: number, force = false) => post<Job>(`/api/books/${id}/capture`, { force }),
  addPages: (id: number) => post<Job>(`/api/books/${id}/add-pages`),
  recutPage: (id: number, pageId: number, force = false) =>
    post<Job>(`/api/books/${id}/pages/${pageId}/recut`, { force }),
  job: (jobId: string) => get<Job>(`/api/jobs/${jobId}`),
  cancelJob: (jobId: string) => post<Job>(`/api/jobs/${jobId}/cancel`),

  // review (C5e)
  groups: (bookId: number) => get<Group[]>(`/api/books/${bookId}/groups`),
  group: (groupId: number) => get<Group>(`/api/groups/${groupId}`),
  groupSamples: (groupId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/groups/${groupId}/samples?offset=${offset}&limit=${limit}`),
  unsure: (bookId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/books/${bookId}/unsure?offset=${offset}&limit=${limit}`),
  deleted: (bookId: number, offset = 0, limit = 200) =>
    get<SamplePage>(`/api/books/${bookId}/unsure?deleted=true&suggest=false&offset=${offset}&limit=${limit}`),
  move: (bookId: number, sampleIds: number[], groupId: number | null) =>
    post<ActionResult>(`/api/books/${bookId}/actions/move`, { sample_ids: sampleIds, group_id: groupId }),
  newGroup: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/new-group`, { sample_ids: sampleIds }),
  merge: (bookId: number, targetId: number, sourceIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/merge`, { target_id: targetId, source_ids: sourceIds }),
  dissolve: (bookId: number, groupId: number) =>
    post<ActionResult>(`/api/books/${bookId}/actions/dissolve`, { group_id: groupId }),
  label: (bookId: number, groupId: number, text: string) =>
    post<ActionResult>(`/api/books/${bookId}/actions/label`, { group_id: groupId, text }),
  status: (bookId: number, groupId: number, change: { reviewed?: boolean; locked?: boolean }) =>
    post<ActionResult>(`/api/books/${bookId}/actions/status`, { group_id: groupId, ...change }),
  deleteSamples: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/delete`, { sample_ids: sampleIds }),
  restoreSamples: (bookId: number, sampleIds: number[]) =>
    post<ActionResult>(`/api/books/${bookId}/actions/restore`, { sample_ids: sampleIds }),
  undo: (bookId: number) => post<ActionResult>(`/api/books/${bookId}/undo`),
  redo: (bookId: number) => post<ActionResult>(`/api/books/${bookId}/redo`),
  history: (bookId: number) => get<HistoryItem[]>(`/api/books/${bookId}/history`),
  // fixing cuts and adding samples (C5f)
  page: (pageId: number) => get<PageDetail>(`/api/pages/${pageId}`),
  crop: (bookId: number, pageId: number, box: [number, number, number, number]) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/crop`, { page_id: pageId, box }),
  join: (bookId: number, sampleIds: number[]) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/join`, { sample_ids: sampleIds }),
  split: (bookId: number, sampleId: number, x: number) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/split`, { sample_id: sampleId, x }),
  upload: (bookId: number, filename: string, data: string) =>
    post<NewSampleResult>(`/api/books/${bookId}/samples/upload`, { filename, data }),

  checkLabel: (text: string, bookId?: number) =>
    get<LabelInfo>(`/api/label?text=${encodeURIComponent(text)}${bookId ? `&book_id=${bookId}` : ""}`),
};

/** Local date and time of a timestamp from the backend (stored in UTC). */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString();
}

/** The contents of a file as base64 (for uploads). */
export async function fileToBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
