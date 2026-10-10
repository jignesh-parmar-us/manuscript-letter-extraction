// One book: the top bar holds a menu of its sections, grouped into the book's two parts (C16a):
// Training Data (Pages & capture, Review groups, Pages, Export dataset) and Read Book (Upload & capture, Book pages,
// Text);
// and its name and the numbers of both parts on one line. Each section is its own screen file.
// The address is #/books/<id>/<section>.
import { useCallback, useEffect, useState } from "react";
import { api, AppInfo, Book, WRITING_LABEL } from "../api";
import AppBar from "../components/AppBar";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";
import Capture from "./Capture";
import Export from "./Export";
import PageViewer from "./PageViewer";
import ReadBook from "./ReadBook";
import Readers from "./Readers";
import TextView from "./TextView";
import Review from "./Review";

export const TABS: { id: string; label: string; part: "Training Data" | "Read Book" }[] = [
  { id: "capture", label: "Pages & capture", part: "Training Data" },
  { id: "review", label: "Review groups", part: "Training Data" },
  { id: "pages", label: "Pages", part: "Training Data" },
  { id: "readers", label: "Readers", part: "Training Data" },
  { id: "export", label: "Export dataset", part: "Training Data" },
  { id: "read", label: "Upload & capture", part: "Read Book" },
  { id: "readpages", label: "Book pages", part: "Read Book" },
  { id: "text", label: "Text", part: "Read Book" },
];
const PARTS = ["Training Data", "Read Book"] as const;

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
      {PARTS.map((part) => (
        <optgroup key={part} label={part}>
          {TABS.filter((t) => t.part === part).map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </optgroup>
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
              · {WRITING_LABEL[book.writing]} ·{" "}
              <span title={`${book.samples} letters · ${book.groups} groups · ${book.labelled} labelled · ${book.unsure} unsure`}>
                Training: {book.pages} pages · {book.reviewed} reviewed letters · {book.unsure} unsure
              </span>{" "}
              | Book: {book.read_pages} pages
            </span>
          </span>
        }
      />
      <main>
        <ErrorBox error={error} onClose={() => setError(null)} />
        {tab === "capture" && <Capture book={book} info={info} onChanged={reload} />}
        {tab === "review" && <Review book={book} view={sub} onChanged={reload} />}
        {tab === "export" && <Export book={book} info={info} />}
        {(tab === "pages" || tab === "readpages") && (
          <PageViewer
            key={tab}
            book={book}
            part={tab === "readpages" ? "read" : "training"}
            pageId={sub && /^\d+$/.test(sub) ? Number(sub) : null}
            sampleId={item && /^\d+$/.test(item) ? Number(item) : null}
            onChanged={reload}
          />
        )}
        {tab === "read" && <ReadBook book={book} info={info} onChanged={reload} />}
        {tab === "readers" && <Readers book={book} onChanged={reload} />}
        {tab === "text" && (
          <TextView book={book} pageId={sub && /^\d+$/.test(sub) ? Number(sub) : null} onChanged={reload} />
        )}
      </main>
    </>
  );
}
