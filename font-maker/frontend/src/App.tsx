// The frame of Font Maker: one bar at the top and the main page. F0 shows which library it reads;
// the book list and font projects come with F1 (font-maker/docs/FONT_PLAN.md).
import { useEffect, useState } from "react";
import { api, AppInfo } from "./api";

export default function App() {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.app().then(setInfo, (e: Error) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="top">
        <div className="top-left">
          <span className="brand">Font Maker</span>
        </div>
        <div className="top-middle" />
        <nav className="top-right" aria-label="App" />
      </header>
      <main>
        {error && (
          <div className="error" role="alert">
            <span>{error}</span>
          </div>
        )}
        {info && (
          <div className="card">
            <p>
              Library: <strong>{info.library}</strong> <span className="muted">(read-only)</span>
            </p>
            <p className="muted">
              {info.books} {info.books === 1 ? "book" : "books"}. Picking a book and building its font come next.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
