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

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

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

// One glyph (font_maker/glyphs.py): made from the group's copies ("average" / "copy") or your "pick".
export interface Glyph {
  group: number;
  book: number;
  code: string;
  kind: string;
  status: Status;
  label_dev: string;
  label_guj: string;
  method: "average" | "copy" | "pick";
  agree: number;
  used: number[];
  count: number; // copies in the group
  image: string;
  left_out: boolean;
  lost: boolean; // your pick was lost: the system pick is used again
  generated: boolean; // made from letters the system generated (the group has no copy cut from a page)
  size: [number, number]; // the image, enlarged 4 times
  // F3, in page pixels against the baseline (+ = below it); "estimated" for glyphs without a line
  bottom: number | null;
  top: number | null;
  width: number | null;
  placed?: "measured" | "estimated";
}

// F3: measured over the font's book (page pixels)
export interface Metrics {
  lines?: number;
  line_height?: number;
  letter_gap?: number | null;
  word_space?: number | null;
}

export interface LostPick {
  group: number;
  label: string;
  sample: number;
  reason: string;
}

export interface GlyphState {
  job: { running: boolean; done: number; total: number; error: string | null; phase?: string };
  glyphs: Glyph[];
  cut_errors: { group: number; code: string; label_dev: string; label_guj: string }[];
  lost: LostPick[];
  metrics: Metrics;
}

export interface Copy {
  id: number;
  book: number;
  image: string;
  generated: boolean;
}

export type Choice = "system" | "copy" | "left_out" | "keep";

// F5: what the font draws in the book's letters (counted from the glyphs, no image is opened)
export interface Coverage {
  base: number;
  aksharas: number;
  generated: number;
  estimated: number;
  left_out: string[];
  duplicates: { group: number; label: string; used: number }[];
  filled: string[];
  missing: string[];
  labels: string[];
}

export interface Report extends Coverage {
  build: number;
  file: string;
  family: string;
  glyphs: number;
  rules: number;
}

// F6: how the newest build draws a text, akshara by akshara (font_maker/tryit.py)
export interface TryAkshara {
  text: string;
  kind: "book" | "pieced" | "filled" | "missing" | "other" | "space";
  start: number; // in the (NFC) text
  detail?: { char: string; kind: "filled" | "missing" }[];
}

// F7: texts the font is measured on after every build (yours, and the books' hand-checked lines)
export interface TestText {
  id: string;
  name: string;
  text: string;
  source: "yours" | "truth";
}

export interface TextCoverage {
  id: string;
  name: string;
  source: "yours" | "truth";
  builds: ({ build: number; aksharas: number; gaps?: [string, number][] } & Record<string, number>)[];
}

export interface TryResult {
  aksharas: TryAkshara[];
  counts: Record<string, number>;
  build: number;
}

export interface BuildState {
  job: { running: boolean; done: number; total: number; error: string | null; phase: string };
  report: Report | null;
  coverage: Coverage;
  builds: number;
  mark_filled: boolean;
}

// Files are loaded by <img> tags, which cannot send the token header: it goes in the address.
export const glyphUrl = (fontId: string, g: Glyph) => `/files/fonts/${fontId}/glyphs/${g.image}?token=${token()}`;
export const copyUrl = (c: Copy) => `/files/books/${c.book}/${c.image}?token=${token()}`;
export const fontFileUrl = (fontId: string, file: string) => `/files/fonts/${fontId}/builds/${file}?token=${token()}`;

export const api = {
  app: () => request<AppInfo>("GET", "/api/app"),
  sources: () => request<Source[]>("GET", "/api/sources"),
  fonts: () => request<Font[]>("GET", "/api/fonts"),
  font: (id: string) => request<Font>("GET", `/api/fonts/${id}`),
  createFont: (name: string, bookId: number, statuses: Status[]) =>
    request<Font>("POST", "/api/fonts", { name, book_id: bookId, statuses }),
  changeFont: (id: string, change: { name?: string; statuses?: Status[]; mark_filled?: boolean }) =>
    request<Font>("PATCH", `/api/fonts/${id}`, change),
  deleteFont: (id: string) => request<void>("DELETE", `/api/fonts/${id}`),
  texts: (id: string) => request<TestText[]>("GET", `/api/fonts/${id}/texts`),
  saveText: (id: string, name: string, text: string) => request<TestText>("PUT", `/api/fonts/${id}/texts`, { name, text }),
  deleteText: (id: string, textId: string) => request<void>("DELETE", `/api/fonts/${id}/texts/${textId}`),
  textsCoverage: (id: string) => request<TextCoverage[]>("GET", `/api/fonts/${id}/coverage/texts`),
  exportText: async (id: string, fmt: "png" | "pdf" | "docx", text: string, size: number): Promise<Blob> => {
    const response = await fetch(`/api/fonts/${id}/export/${fmt}`, {
      method: "POST",
      headers: { "X-Token": token(), "Content-Type": "application/json" },
      body: JSON.stringify({ text, size }),
    });
    if (!response.ok) {
      let detail = response.statusText || `Error ${response.status}`;
      try {
        detail = (await response.json()).detail ?? detail;
      } catch {
        // not JSON
      }
      throw new Error(detail);
    }
    return response.blob();
  },
  tryText: (id: string, text: string) => request<TryResult>("POST", `/api/fonts/${id}/coverage`, { text }),
  buildState: (id: string) => request<BuildState>("GET", `/api/fonts/${id}/build`),
  build: (id: string) => request<BuildState>("POST", `/api/fonts/${id}/build`),
  fill: (id: string, chars: string[], filled: boolean) => request<BuildState>("PUT", `/api/fonts/${id}/filled`, { chars, filled }),
  checkGlyphs: (id: string) => request<GlyphState>("POST", `/api/fonts/${id}/glyphs/check`),
  glyphs: (id: string) => request<GlyphState>("GET", `/api/fonts/${id}/glyphs`),
  outline: (id: string, group: number) =>
    request<{ d: string; size: [number, number]; contours: number }>("GET", `/api/fonts/${id}/glyphs/${group}/outline`),
  copies: (id: string, group: number) => request<Copy[]>("GET", `/api/fonts/${id}/glyphs/${group}/copies`),
  choose: (id: string, group: number, choice: Choice, sample?: number) =>
    request<{ glyph: Glyph | null; lost: LostPick[] }>("PUT", `/api/fonts/${id}/glyphs/${group}/choice`, { choice, sample }),
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
