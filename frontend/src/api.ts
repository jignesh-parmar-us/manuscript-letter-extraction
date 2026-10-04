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
};

/** Local date and time of a timestamp from the backend (stored in UTC). */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString();
}
