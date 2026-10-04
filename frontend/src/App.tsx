// The frame of the app: a header with the library folder, and the screen chosen by the address:
//   #/                 Books       (screens/Books.tsx)
//   #/books/<id>/...   one book    (screens/BookView.tsx, with its own tabs)
import { useEffect, useState } from "react";
import { api, AppInfo } from "./api";
import ErrorBox from "./components/ErrorBox";
import { go, useRoute } from "./route";
import Books from "./screens/Books";
import BookView from "./screens/BookView";

export default function App() {
  const route = useRoute();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.app().then(setInfo, setError);
  }, []);

  const bookId = route[0] === "books" && route[1] ? Number(route[1]) : null;

  return (
    <div className="app">
      <header className="top">
        <button className="brand link" onClick={() => go("/")}>
          Manuscript Letters
        </button>
        {info && (
          <span className="muted small" title="Library folder">
            {info.library}
          </span>
        )}
      </header>
      <main>
        <ErrorBox error={error} onClose={() => setError(null)} />
        {bookId !== null && !Number.isNaN(bookId) ? (
          <BookView bookId={bookId} tab={route[2] ?? "capture"} sub={route[3]} info={info} />
        ) : (
          <Books info={info} onLibraryChanged={() => api.app().then(setInfo, setError)} />
        )}
      </main>
    </div>
  );
}
