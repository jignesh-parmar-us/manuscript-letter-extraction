// Books screen (C20, own screen in C21): the library's books, what is read into text, and New book: writing,
// name, the dataset it learns from, then its pages uploaded (images or a PDF; a PDF becomes page images in
// the book folder). The datasets have their own screen (Datasets.tsx).
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, AppInfo, BookSummary, localTime, Writing, WRITING_LABEL } from "../api";
import WritingChoice from "../components/WritingChoice";
import ErrorBox from "../components/ErrorBox";
import { AppFolders, useRowEditing } from "../components/RowList";
import { filesProblem, PageFilePicker, uploadPages } from "../components/UploadPages";
import { go } from "../route";

interface Props {
  info: AppInfo | null;
  onLibraryChanged: () => void;
}

export default function Books({ info, onLibraryChanged }: Props) {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [datasets, setDatasets] = useState<BookSummary[]>([]);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.books().then(setBooks, setError);
    api.datasets().then(setDatasets, setError);
  }, []);
  useEffect(load, [load]);
  const { dialog, nameCell, actions } = useRowEditing(load, setError);

  return (
    <section>
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <h1>Books</h1>
      <p className="muted small">
        What is read into text. A book learns from a dataset (see{" "}
        <button className="link" onClick={() => go("/datasets")}>
          Datasets
        </button>
        ).
      </p>
      {books === null ? (
        <p className="muted">Loading…</p>
      ) : books.length === 0 ? (
        <p className="muted">No books yet. Create the first one below.</p>
      ) : (
        <table className="list" aria-label="Books">
          <thead>
            <tr>
              <th>Book</th>
              <th className="num">Pages</th>
              <th>Learns from</th>
              <th>Last change</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {books.map((b) => (
              <tr key={b.id}>
                <td>{nameCell(b, WRITING_LABEL[b.writing])}</td>
                <td className="num">{b.read_pages}</td>
                <td>
                  {b.dataset_id ? (
                    <button className="link" onClick={() => go(`/books/${b.dataset_id}`)}>
                      {b.dataset_name}
                    </button>
                  ) : (
                    <span className="muted small">no dataset</span>
                  )}
                </td>
                <td className="small">{localTime(b.updated_at)}</td>
                {actions(b)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewBook datasets={datasets} onError={(e) => { setError(e); load(); }} />
      <AppFolders info={info} onChanged={onLibraryChanged} onError={setError} />
    </section>
  );
}

function NewBook(props: { datasets: BookSummary[]; onError: (e: unknown) => void }) {
  const [name, setName] = useState("");
  const [writing, setWriting] = useState<Writing>("handwritten");
  const [dataset, setDataset] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState("");
  const fitting = props.datasets.filter((d) => d.writing === writing);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setProgress("Creating the book…");
    let made: number | null = null;
    try {
      made = (await api.createBook(name.trim(), writing, dataset)).id;
      await uploadPages("book", made, files, (n, total, file) => setProgress(`Uploading ${n + 1} of ${total}: ${file}`));
      go(`/books/${made}/read`);
    } catch (err) {
      setProgress("");
      props.onError(made === null ? err
        : new Error(`The book "${name.trim()}" was made, but its pages were not all uploaded: ${(err as Error).message} ` +
          "Open it to upload the rest in Prepare."));
    }
  }

  const busy = Boolean(progress);
  return (
    <form className="card" onSubmit={submit}>
      <h2>New book</h2>
      <WritingChoice value={writing} onChange={(w) => { setWriting(w); setDataset(null); }} />
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: Vachanamrut, part 1" required />
      </label>
      <label className="field">
        <span>Learns from</span>
        <select aria-label="Learns from" value={dataset ?? ""}
          onChange={(e) => setDataset(e.target.value ? Number(e.target.value) : null)}>
          <option value="">no dataset yet</option>
          {fitting.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.reviewed} reviewed letters)
            </option>
          ))}
        </select>
      </label>
      <PageFilePicker files={files} onChange={setFiles} disabled={busy} />
      <p className="muted small">
        Several page images, or one PDF (its pages become images). They are kept in the uploads folder. Then prepare
        the pages for reading in Prepare.
      </p>
      <div className="row">
        <button className="primary" type="submit" disabled={busy || !name.trim() || Boolean(filesProblem(files))}>
          Create book
        </button>
        {progress && <span className="small muted">{progress}</span>}
      </div>
    </form>
  );
}
