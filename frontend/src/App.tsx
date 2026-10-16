// The frame of the app: one bar at the top (components/AppBar.tsx), and the screen chosen by the address:
//   #/                 Books       (screens/Books.tsx)
//   #/datasets         Datasets    (screens/Datasets.tsx, C21)
//   #/books/<id>/...   one book or dataset (screens/BookView.tsx, with its own tabs)
import { useEffect, useState } from "react";
import { api, AppInfo } from "./api";
import ErrorBox from "./components/ErrorBox";
import AppBar from "./components/AppBar";
import { go, useRoute } from "./route";
import Books from "./screens/Books";
import BookView from "./screens/BookView";
import Datasets from "./screens/Datasets";

export default function App() {
  const route = useRoute();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.app().then(setInfo, setError);
  }, []);

  const bookId = route[0] === "books" && route[1] ? Number(route[1]) : null;

  const inBook = bookId !== null && !Number.isNaN(bookId);
  const onDatasets = route[0] === "datasets";
  const reload = () => api.app().then(setInfo, setError);
  return (
    <div className="app">
      {inBook ? (
        // the book screen draws the bar itself: it holds the book's section menu and numbers
        <BookView bookId={bookId!} tab={route[2] ?? "capture"} sub={route[3]} item={route[4]} info={info} />
      ) : (
        <>
          <AppBar
            info={info}
            current={onDatasets ? "datasets" : "books"}
            left={
              <button className="brand link" onClick={() => go("/")}>
                Manuscript Letters
              </button>
            }
          />
          <main>
            <ErrorBox error={error} onClose={() => setError(null)} />
            {onDatasets ? (
              <Datasets info={info} onLibraryChanged={reload} />
            ) : (
              <Books info={info} onLibraryChanged={reload} />
            )}
          </main>
        </>
      )}
    </div>
  );
}
