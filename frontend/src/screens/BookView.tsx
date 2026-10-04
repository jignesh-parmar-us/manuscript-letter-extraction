// One book: its name and numbers on top, and tabs for the work on it.
// Each tab is its own screen file; the address is #/books/<id>/<tab>.
import { useCallback, useEffect, useState } from "react";
import { api, AppInfo, Book } from "../api";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";
import Capture from "./Capture";

export const TABS: { id: string; label: string }[] = [{ id: "capture", label: "Pages & capture" }];

interface Props {
  bookId: number;
  tab: string;
  info: AppInfo | null;
}

export default function BookView({ bookId, tab, info }: Props) {
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(() => {
    api.book(bookId).then(setBook, setError);
  }, [bookId]);
  useEffect(reload, [reload]);

  if (!book) {
    return (
      <section>
        <ErrorBox error={error} />
        {!error && <p className="muted">Loading…</p>}
        <button onClick={() => go("/")}>Back to the books</button>
      </section>
    );
  }

  return (
    <section>
      <div className="row between">
        <div>
          <button className="link small" onClick={() => go("/")}>
            ← Books
          </button>
          <h1>{book.name}</h1>
          <p className="muted small">
            {book.pages} pages · {book.samples} letters · {book.groups} groups · {book.labelled} labelled ·{" "}
            {book.unsure} unsure
          </p>
        </div>
      </div>
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === tab ? "tab active" : "tab"} onClick={() => go(`/books/${bookId}/${t.id}`)}>
            {t.label}
          </button>
        ))}
      </nav>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {tab === "capture" && <Capture book={book} info={info} onChanged={reload} />}
    </section>
  );
}
