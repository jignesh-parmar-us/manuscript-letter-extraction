// Books screen: every book of the library, and a form to create a new one.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, AppInfo, BookSummary, localTime, Writing } from "../api";
import WritingChoice from "../components/WritingChoice";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";

interface Props {
  info: AppInfo | null;
  onLibraryChanged: () => void;
}

export default function Books({ info, onLibraryChanged }: Props) {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);

  const load = useCallback(() => {
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

  async function remove(book: BookSummary) {
    const ok = await confirm(
      `Delete "${book.name}" with all its groups and labels? The input pages are not touched.`,
      "Delete",
    );
    if (!ok) return;
    try {
      await api.deleteBook(book.id);
      load();
    } catch (e) {
      setError(e);
    }
  }

  return (
    <section>
      {dialog}
      <h1>Books</h1>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {books === null ? (
        <p className="muted">Loading…</p>
      ) : books.length === 0 ? (
        <p className="muted">No books yet. Create the first one below.</p>
      ) : (
        <table className="list">
          <thead>
            <tr>
              <th>Book</th>
              <th className="num">Pages</th>
              <th className="num">Letters</th>
              <th className="num">Groups</th>
              <th className="num">Labelled</th>
              <th className="num">Unsure</th>
              <th>Last change</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {books.map((b) => (
              <tr key={b.id}>
                <td>
                  {renaming?.id === b.id ? (
                    <form className="row" onSubmit={saveName}>
                      <input
                        aria-label="New name"
                        value={renaming.name}
                        onChange={(e) => setRenaming({ id: b.id, name: e.target.value })}
                        autoFocus
                      />
                      <button className="primary" type="submit" disabled={!renaming.name.trim()}>
                        Save
                      </button>
                      <button type="button" onClick={() => setRenaming(null)}>
                        Cancel
                      </button>
                    </form>
                  ) : (
                    <button className="link strong" onClick={() => go(`/books/${b.id}`)}>
                      {b.name}
                    </button>
                  )}
                  <div className="muted small">{b.input_dir}</div>
                </td>
                <td className="num">{b.pages}</td>
                <td className="num">{b.samples}</td>
                <td className="num">{b.groups}</td>
                <td className="num">
                  {b.labelled}
                  {b.groups > 0 && <span className="muted"> ({Math.round((100 * b.labelled) / b.groups)}%)</span>}
                </td>
                <td className="num">{b.unsure}</td>
                <td className="small">{localTime(b.updated_at)}</td>
                <td className="actions">
                  <button onClick={() => go(`/books/${b.id}`)}>Open</button>
                  <button onClick={() => setRenaming({ id: b.id, name: b.name })}>Rename</button>
                  <button className="danger" onClick={() => remove(b)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewBook info={info} onCreated={(id) => go(`/books/${id}`)} onError={setError} />
      <LibraryFolder info={info} onChanged={onLibraryChanged} onError={setError} />
    </section>
  );
}

function FolderField(props: { value: string; onChange: (v: string) => void; info: AppInfo | null; label: string }) {
  async function browse() {
    const { path } = await api.pickFolder();
    if (path) props.onChange(path);
  }
  return (
    <label className="field">
      <span>{props.label}</span>
      <span className="row">
        <input
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          placeholder="/path/to/the/page/images"
          required
        />
        {props.info?.can_pick_folder && (
          <button type="button" onClick={browse}>
            Browse…
          </button>
        )}
      </span>
    </label>
  );
}

function NewBook(props: { info: AppInfo | null; onCreated: (id: number) => void; onError: (e: unknown) => void }) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [writing, setWriting] = useState<Writing>("handwritten");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const book = await api.createBook(name.trim(), folder.trim(), writing);
      props.onCreated(book.id);
    } catch (err) {
      props.onError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>New book</h2>
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: Vachanamrut, part 1" required />
      </label>
      <FolderField label="Folder with the page images" value={folder} onChange={setFolder} info={props.info} />
      <WritingChoice value={writing} onChange={setWriting} />
      <p className="muted small">The page images are only read, never changed.</p>
      <button className="primary" type="submit" disabled={busy || !name.trim() || !folder.trim()}>
        Create book
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
