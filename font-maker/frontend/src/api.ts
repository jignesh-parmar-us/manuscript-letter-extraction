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

export async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { "X-Token": token() } });
  if (!response.ok) {
    let detail = response.statusText || `Error ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      // not JSON: keep the status text
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export interface AppInfo {
  name: string;
  version: string;
  library: string;
  books: number;
}

export const api = {
  app: () => get<AppInfo>("/api/app"),
};
