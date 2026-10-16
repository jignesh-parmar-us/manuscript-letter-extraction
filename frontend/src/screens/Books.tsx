// Books screen (C20): the library's books (what is read) and datasets (what is cut, grouped and labelled; books
// learn from them), and a form to create either. C21 gives each its own screen and uploads.
import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { api, AppInfo, BookSummary, Kind, localTime, Writing, WRITING_LABEL } from "../api";
import WritingChoice from "../components/WritingChoice";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import FolderField from "../components/FolderField";
import { go } from "../route";

interface Props {
  info: AppInfo | null;
  onLibraryChanged: () => void;
}

export default function Books({ info, onLibraryChanged }: Props) {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [datasets, setDatasets] = useState<BookSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);

  const load = useCallback(() => {
    api.datasets().then(setDatasets, setError);
    api.books().then(setBooks, setError);
  }, []);
  useEffect(load, [load]);

  async function saveName(e: FormEvent) {
    e.preventDefault();
    if (!renaming) return;
    try {
      await api.renameBook(renaming.id, renaming.name.trim());
      setRenaming(null);
      load();
    } catch (err) {
      setError(err);
    }
  }

  async function remove(row: BookSummary) {
    const users = row.used_by ?? [];
    const ok = await confirm(
      row.kind === "book"
        ? `Delete the book "${row.name}" with its pages' text, line truth and our reader? Its dataset and the page images are not touched.`
        : `Delete the dataset "${row.name}" with all its groups and labels? The input pages are not touched.` +
            (users.length ? ` ${users.map((u) => `"${u.name}"`).join(", ")} learn from it and will learn from nothing.` : ""),
      "Delete",
    );
    if (!ok) return;
    try {
      await api.deleteBook(row.id);
      load();
    } catch (e) {
      setError(e);
    }
  }

  const nameCell = (b: BookSummary, below: ReactNode) =>
    renaming?.id === b.id ? (
      <form className="row" onSubmit={saveName}>
        <input aria-label="New name" value={renaming.name} onChange={(e) => setRenaming({ id: b.id, name: e.target.value })}
          autoFocus />
        <button className="primary" type="submit" disabled={!renaming.name.trim()}>
          Save
        </button>
        <button type="button" onClick={() => setRenaming(null)}>
          Cancel
        </button>
      </form>
    ) : (
      <>
        <button className="link strong" onClick={() => go(`/books/${b.id}`)}>
          {b.name}
        </button>
        <div className="muted small">{below}</div>
      </>
    );
  const actions = (b: BookSummary) => (
    <td className="actions">
      <button onClick={() => go(`/books/${b.id}`)}>Open</button>
      <button onClick={() => setRenaming({ id: b.id, name: b.name })}>Rename</button>
      <button className="danger" onClick={() => remove(b)}>
        Delete
      </button>
    </td>
  );

  return (
    <section>
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <h1>Books</h1>
      <p className="muted small">What is read into text. A book learns from a dataset.</p>
      {books === null ? (
        <p className="muted">Loading…</p>
      ) : books.length === 0 ? (
        <p className="muted">No books yet.</p>
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
      <h1>Datasets</h1>
      <p className="muted small">Pages whose letters are cut, grouped, reviewed and labelled: what books learn from.</p>
      {datasets === null ? (
        <p className="muted">Loading…</p>
      ) : datasets.length === 0 ? (
        <p className="muted">No datasets yet. Create the first one below.</p>
      ) : (
        <table className="list" aria-label="Datasets">
          <thead>
            <tr>
              <th>Dataset</th>
              <th className="num">Pages</th>
              <th className="num">Letters</th>
              <th className="num">Groups</th>
              <th className="num">Labelled</th>
              <th className="num">Unsure</th>
              <th>Used by</th>
              <th>Last change</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datasets.map((b) => (
              <tr key={b.id}>
                <td>{nameCell(b, b.input_dir)}</td>
                <td className="num">{b.pages}</td>
                <td className="num">{b.samples}</td>
                <td className="num">{b.groups}</td>
                <td className="num">
                  {b.labelled}
                  {b.groups > 0 && <span className="muted"> ({Math.round((100 * b.labelled) / b.groups)}%)</span>}
                </td>
                <td className="num">{b.unsure}</td>
                <td className="small">{(b.used_by ?? []).map((u) => u.name).join(", ") || <span className="muted">—</span>}</td>
                <td className="small">{localTime(b.updated_at)}</td>
                {actions(b)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewRow datasets={datasets ?? []} onCreated={(id) => go(`/books/${id}`)} onError={setError} />
      <LibraryFolder info={info} onChanged={onLibraryChanged} onError={setError} />
    </section>
  );
}

function NewRow(props: { datasets: BookSummary[]; onCreated: (id: number) => void; onError: (e: unknown) => void }) {
  const [kind, setKind] = useState<Kind>("dataset");
  const [name, setName] = useState("");
  const [writing, setWriting] = useState<Writing>("handwritten");
  const [dataset, setDataset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const fitting = props.datasets.filter((d) => d.writing === writing);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const made = kind === "book" ? await api.createBook(name.trim(), writing, dataset)
        : await api.createDataset(name.trim(), writing);
      props.onCreated(made.id);
    } catch (err) {
      props.onError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>New</h2>
      <div className="row" role="radiogroup" aria-label="What to make">
        <label className="row">
          <input type="radio" name="kind" checked={kind === "dataset"} onChange={() => setKind("dataset")} />
          Dataset <span className="muted small">(sample pages to cut, group and label)</span>
        </label>
        <label className="row">
          <input type="radio" name="kind" checked={kind === "book"} onChange={() => setKind("book")} />
          Book <span className="muted small">(pages to read into text)</span>
        </label>
      </div>
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: Vachanamrut, part 1" required />
      </label>
      <WritingChoice value={writing} onChange={setWriting} />
      {kind === "book" && (
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
      )}
      <p className="muted small">
        {kind === "book"
          ? "The pages to read come next, in Prepare."
          : "The page images come next, in Pages & capture."}
      </p>
      <button className="primary" type="submit" disabled={busy || !name.trim()}>
        {kind === "book" ? "Create book" : "Create dataset"}
      </button>
    </form>
  );
}

function LibraryFolder(props: { info: AppInfo | null; onChanged: () => void; onError: (e: unknown) => void }) {
  const [open, setOpen] = useState(false);
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");
  if (!props.info) return null;

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api.chooseLibrary(folder.trim());
      setMessage(r.restart_needed ? "Saved. Close and start the app again to use this library." : "Saved.");
      props.onChanged();
    } catch (err) {
      props.onError(err);
    }
  }

  return (
    <div className="card subtle">
      <p className="small">
        Library folder: <code>{props.info.library}</code>{" "}
        {!open && (
          <button className="link" onClick={() => setOpen(true)}>
            change…
          </button>
        )}
      </p>
      {open && (
        <form onSubmit={save}>
          <FolderField label="New library folder" value={folder} onChange={setFolder} info={props.info} />
          <button type="submit" disabled={!folder.trim()}>
            Save
          </button>
          {message && <p className="small">{message}</p>}
        </form>
      )}
    </div>
  );
}
