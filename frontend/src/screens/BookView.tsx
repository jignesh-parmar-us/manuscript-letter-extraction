// One dataset or book (C20: separate rows; before, one book held both parts, C16a): the top bar holds a menu of
// its sections and its name and numbers on one line. A dataset has the Training Data sections (Pages & capture,
// Review groups, Pages, Letter checker, Export dataset), a book the Read Book ones (Prepare, Book pages, Text,
// Dictionary, Line truth) and a link to the dataset it learns from. Each section is its own screen file.
// The address is #/books/<id>/<section>, for both kinds; a section of the other kind opens the first of its own.
import { useCallback, useEffect, useState } from "react";
import { api, AppInfo, Book, Kind, WRITING_LABEL } from "../api";
import AppBar from "../components/AppBar";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";
import Capture from "./Capture";
import Export from "./Export";
import PageViewer from "./PageViewer";
import ReadBook from "./ReadBook";
import Dictionary from "./Dictionary";
import Readers from "./Readers";
import TruthView from "./TruthView";
import TextView from "./TextView";
import Review from "./Review";

export const TABS: { id: string; label: string; part: "Training Data" | "Read Book" }[] = [
  { id: "capture", label: "Pages & capture", part: "Training Data" },
  { id: "review", label: "Review groups", part: "Training Data" },
  { id: "pages", label: "Pages", part: "Training Data" },
  { id: "readers", label: "Letter checker", part: "Training Data" },
  { id: "export", label: "Export dataset", part: "Training Data" },
  { id: "read", label: "Prepare", part: "Read Book" },
  { id: "readpages", label: "Book pages", part: "Read Book" },
  { id: "text", label: "Text", part: "Read Book" },
  { id: "dictionary", label: "Dictionary", part: "Read Book" },
  { id: "truth", label: "Line truth", part: "Read Book" },
];
const PART_OF: Record<Kind, "Training Data" | "Read Book"> = { dataset: "Training Data", book: "Read Book" };

/** The sections of a dataset or of a book. */
export const tabsOf = (kind: Kind) => TABS.filter((t) => t.part === PART_OF[kind]);

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

  const kind: Kind = book?.kind ?? "dataset";
  const own = tabsOf(kind);
  const wrongTab = book !== null && !own.some((t) => t.id === tab);
  useEffect(() => {
    if (wrongTab) go(`/books/${bookId}/${own[0].id}`);
  }, [wrongTab, bookId]); // eslint-disable-line react-hooks/exhaustive-deps

  const section = (
    <select
      className="section-menu"
      aria-label="Section"
      value={tab}
      onChange={(e) => go(`/books/${bookId}/${e.target.value}`)}
    >
      <optgroup label={kind === "book" ? "Book" : "Dataset"}>
        {(book ? own : TABS).map((t) => (
          <option key={t.id} value={t.id}>
            {t.label}
          </option>
        ))}
      </optgroup>
    </select>
  );

  if (!book || wrongTab) {
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
              · {kind === "book" ? "Book" : "Dataset"} · {WRITING_LABEL[book.writing]} ·{" "}
              {kind === "book" ? (
                <>
                  {book.read_pages} pages · learns from{" "}
                  {book.dataset_id ? (
                    <button className="link small" onClick={() => go(`/books/${book.dataset_id}`)}>
                      {book.dataset_name}
                    </button>
                  ) : (
                    "no dataset yet"
                  )}
                </>
              ) : (
                <>
                  <span title={`${book.samples} letters · ${book.groups} groups · ${book.labelled} labelled · ${book.unsure} unsure`}>
                    {book.pages} pages · {book.reviewed} reviewed letters · {book.unsure} unsure
                  </span>
                  {(book.used_by ?? []).length > 0 && <> · used by {book.used_by.map((u) => u.name).join(", ")}</>}
                </>
              )}
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
        {tab === "dictionary" && <Dictionary book={book} onChanged={reload} />}
        {tab === "truth" && <TruthView book={book} pageId={sub && /^\d+$/.test(sub) ? Number(sub) : null} />}
        {tab === "text" && (
          <TextView book={book} pageId={sub && /^\d+$/.test(sub) ? Number(sub) : null} onChanged={reload} />
        )}
      </main>
    </>
  );
}
