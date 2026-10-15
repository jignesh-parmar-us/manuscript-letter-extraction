// The one way Font Maker's screens talk to its backend (font_maker/api.py).
// Every request carries the session token the backend wrote into the page (window.__TOKEN__).
// A failed request throws an Error with the backend's message (`detail`).

declare global {
  interface Window {
    __TOKEN__?: string;
  }
}

export function token(): string {
  return window.__TOKEN__ ?? new URLSearchParams(window.location.search).get("token") ?? "";
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
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      // not JSON: keep the status text
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface AppInfo {
  name: string;
  version: string;
  library: string;
  books: number;
}

// The group statuses a font can take its glyphs from (font_maker/projects.py STATUSES).
export type Status = "labelled" | "auto";

export const STATUS_TEXT: Record<Status, string> = {
  labelled: "Reviewed and labelled",
  auto: "Not reviewed yet, with a suggested label",
};

export interface Source {
  id: number;
  name: string;
  writing: string;
  samples: number;
  groups: { auto: number; reviewed: number; labelled: number };
  usable: Record<Status, number>; // groups with a one-akshara label: they can become a glyph
}

export interface Font {
  id: string;
  name: string;
  sources: number[];
  statuses: Status[];
  builds: number;
  last_build: string | null;
  created_at: string;
  updated_at: string;
}

export const api = {
  app: () => request<AppInfo>("GET", "/api/app"),
  sources: () => request<Source[]>("GET", "/api/sources"),
  fonts: () => request<Font[]>("GET", "/api/fonts"),
  font: (id: string) => request<Font>("GET", `/api/fonts/${id}`),
  createFont: (name: string, bookId: number, statuses: Status[]) =>
    request<Font>("POST", "/api/fonts", { name, book_id: bookId, statuses }),
  changeFont: (id: string, change: { name?: string; statuses?: Status[] }) =>
    request<Font>("PATCH", `/api/fonts/${id}`, change),
  deleteFont: (id: string) => request<void>("DELETE", `/api/fonts/${id}`),
};

// How many groups of a book a font with these statuses can use.
export function usable(source: Source | undefined, statuses: Status[]): number {
  return source ? statuses.reduce((n, s) => n + source.usable[s], 0) : 0;
}

export function deleteMessage(font: Font): string {
  const builds = font.builds === 1 ? "Its 1 build is" : `Its ${font.builds} builds are`;
  return (
    `Delete the font "${font.name}"? ${builds} deleted too. ` +
    "The book's groups, samples and labels are not changed. A copy installed on this Mac stays installed."
  );
}
