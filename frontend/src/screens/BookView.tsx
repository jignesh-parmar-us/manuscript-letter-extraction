// One book: the top bar holds a menu of its sections (Pages & capture, Review groups, Pages, Export)
// and its name and numbers on one line; each section is its own screen file.
// The address is #/books/<id>/<section>.
import { useCallback, useEffect, useState } from "react";
import { api, AppInfo, Book, WRITING_LABEL } from "../api";
import AppBar from "../components/AppBar";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";
import Capture from "./Capture";
import Export from "./Export";
import PageViewer from "./PageViewer";
import Review from "./Review";

export const TABS: { id: string; label: string }[] = [
  { id: "capture", label: "Pages & capture" },
  { id: "review", label: "Review groups" },
  { id: "pages", label: "Pages" },
  { id: "export", label: "Export" },
];

interface Props {
  bookId: number;
  tab: string;
  sub?: string; // e.g. the group shown in the Review tab
  item?: string; // e.g. the sample shown on the page in the Pages tab
  info: AppInfo | null;
}

export default function BookView({ bookId, tab, sub, item, info }: Props) {
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(() => {
    api.book(bookId).then(setBook, setError);
  }, [bookId]);
  useEffect(reload, [reload]);

  const section = (
    <select
      className="section-menu"
      aria-label="Section"
      value={tab}
      onChange={(e) => go(`/books/${bookId}/${e.target.value}`)}
    >
      {TABS.map((t) => (
        <option key={t.id} value={t.id}>
          {t.label}
        </option>
      ))}
    </select>
  );

  if (!book) {
    return (
      <>
        <AppBar info={info} left={section} middle={<span className="muted small">Loading…</span>} />
        <main>
          <ErrorBox error={error} />
        </main>
      </>
    );
  }

  return (
    <>
      <AppBar
        info={info}
        left={section}
        middle={
          <span className="book-line" title={book.input_dir}>
            <strong>{book.name}</strong>
            <span className="muted small">
              {" "}
              · {WRITING_LABEL[book.writing]} · {book.pages} pages · {book.samples} letters · {book.groups} groups ·{" "}
              {book.labelled} labelled · {book.unsure} unsure
            </span>
          </span>
        }
      />
      <main>
        <ErrorBox error={error} onClose={() => setError(null)} />
        {tab === "capture" && <Capture book={book} info={info} onChanged={reload} />}
        {tab === "review" && <Review book={book} view={sub} onChanged={reload} />}
        {tab === "export" && <Export book={book} info={info} />}
        {tab === "pages" && (
          <PageViewer
            book={book}
            pageId={sub && /^\d+$/.test(sub) ? Number(sub) : null}
            sampleId={item && /^\d+$/.test(item) ? Number(item) : null}
            onChanged={reload}
          />
        )}
      </main>
    </>
  );
}
