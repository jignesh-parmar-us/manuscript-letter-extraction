// What the Books and Datasets screens (C21) share: renaming and deleting a row in its list, and the card with
// the library and uploads folders, and the notice of the page images moved into the uploads folder (C26).
import { FormEvent, ReactNode, useCallback, useState } from "react";
import { api, AppInfo, BookSummary, Job, Kind } from "../api";
import { useJob } from "./useJob";
import { useConfirm } from "./Confirm";
import FolderField from "./FolderField";
import { go } from "../route";

/** The name cell (inline rename) and the Open / Rename / Delete cell of a row, and the confirm dialog. */
export function useRowEditing(reload: () => void, onError: (e: unknown) => void) {
  const [dialog, confirm] = useConfirm();
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);

  async function saveName(e: FormEvent) {
    e.preventDefault();
    if (!renaming) return;
    try {
      await api.renameBook(renaming.id, renaming.name.trim());
      setRenaming(null);
      reload();
    } catch (err) {
      onError(err);
    }
  }

  async function remove(row: BookSummary) {
    const users = row.used_by ?? [];
    const ok = await confirm(
      (row.kind === "book"
        ? `Delete the book "${row.name}" with its pages' text, line truth and our reader? Its dataset is not touched.`
        : `Delete the dataset "${row.name}" with all its groups and labels?` +
          (users.length ? ` ${users.map((u) => `"${u.name}"`).join(", ")} learn from it and will learn from nothing.` : "")) +
        " Pages uploaded into it are deleted too; pages in a folder of your own are not touched.",
      "Delete",
    );
    if (!ok) return;
    try {
      await api.deleteBook(row.id);
      reload();
    } catch (e) {
      onError(e);
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

  return { dialog, nameCell, actions };
}

/** Links to the datasets a book learns from (C23: one or more), or "no dataset yet". */
export function DatasetLinks({ datasets, small = false }: { datasets: { id: number; name: string }[]; small?: boolean }) {
  if (!datasets.length) return <span className="muted small">no dataset yet</span>;
  return (
    <>
      {datasets.map((d, i) => (
        <span key={d.id}>
          {i > 0 && ", "}
          <button className={small ? "link small" : "link"} onClick={() => go(`/books/${d.id}`)}>
            {d.name}
          </button>
        </span>
      ))}
    </>
  );
}

/** The library folder and the uploads folder (where uploaded pages are kept), each changeable. A new uploads
 *  folder takes the pages uploaded before with it (C26, a job): the setting is kept only when that worked. */
export function AppFolders(props: { info: AppInfo | null; onChanged: () => void; onError: (e: unknown) => void }) {
  const [open, setOpen] = useState<"" | "library" | "uploads">("");
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");
  const { onChanged, onError } = props;
  const ended = useCallback((j: Job) => {
    if (j.status === "done") {
      setMessage(`Saved. ${j.result?.files ?? 0} uploaded page files were moved there; the old folder ` +
        `${j.result?.old ?? ""} was left as it is.`);
      onChanged();
    } else if (j.status === "failed") {
      setMessage("");
      onError(new Error(`The uploads folder was not changed: ${j.error}`));
    } else {
      setMessage("Cancelled: the uploads folder was not changed.");
    }
  }, [onChanged, onError]);
  const [job, setJob] = useJob(null, ended);
  if (!props.info) return null;
  const moving = job?.status === "running";

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      if (open === "library") {
        const r = await api.chooseLibrary(folder.trim());
        setMessage(r.restart_needed ? "Saved. Close and start the app again to use this library." : "Saved.");
        props.onChanged();
      } else {
        const r = await api.chooseUploads(folder.trim());
        if (r.job) {
          setMessage("");
          setJob(r.job);
        } else {
          setMessage("Saved. Uploads go there from now on.");
          props.onChanged();
        }
      }
    } catch (err) {
      props.onError(err);
    }
  }

  const change = (which: "library" | "uploads") =>
    !open && (
      <button className="link" onClick={() => { setOpen(which); setFolder(""); setMessage(""); }}>
        change…
      </button>
    );

  return (
    <div className="card subtle">
      <p className="small">
        Library folder: <code>{props.info.library}</code> {change("library")}
      </p>
      {props.info.uploads && (
        <p className="small">
          Uploaded pages are kept in: <code>{props.info.uploads}</code> {change("uploads")}
        </p>
      )}
      {open && (
        <form onSubmit={save}>
          <FolderField label={open === "library" ? "New library folder" : "New uploads folder"} value={folder}
            onChange={setFolder} info={props.info} />
          <div className="row">
            <button type="submit" disabled={!folder.trim() || moving}>
              Save
            </button>
            <button type="button" disabled={moving} onClick={() => setOpen("")}>
              Close
            </button>
            {moving && (
              <span className="small muted">
                Moving the uploaded pages: {job.done} of {job.total} {job.current}
              </span>
            )}
          </div>
          {open === "uploads" && !message && !moving && (
            <p className="small muted">The pages uploaded before are copied there too, checked, and used from there; the old folder is left as it is.</p>
          )}
          {message && <p className="small">{message}</p>}
        </form>
      )}
    </div>
  );
}

/** Once, after the app moved the page images of the older rows into the uploads folder at its start (C26): what was
 *  moved, the database backup, the folders no row uses any more, and the rows that could not be moved. */
const KIND_NAME: Record<Kind, string> = { dataset: "Dataset", book: "Book" };

export function PageMoveNote(props: { info: AppInfo | null; onSeen: () => void }) {
  const n = props.info?.page_move;
  if (!n) return null;
  const files = n.moved.reduce((t, m) => t + m.files, 0);
  async function seen() {
    try {
      await api.pageMoveSeen();
    } finally {
      props.onSeen();
    }
  }
  return (
    <div className="card notice" role="status" aria-label="Page images moved">
      {n.moved.length > 0 && (
        <>
          <p>
            <strong>The page images now are in the uploads folder.</strong> {files} files of {n.moved.length}{" "}
            {n.moved.length === 1 ? "row were" : "rows were"} copied there, each checked against its original; nothing
            else changed. The originals were not touched.
          </p>
          <ul className="small">
            {n.moved.map((m) => (
              <li key={m.id}>
                {KIND_NAME[m.kind]} {m.name}: {m.files} files from <code>{m.from}</code>
              </li>
            ))}
          </ul>
          {n.old_folders.length > 0 && (
            <p className="small">
              No dataset or book uses these folders any more; you can remove them when you like:{" "}
              {n.old_folders.map((f) => <code key={f}>{f} </code>)}
            </p>
          )}
          {n.backup && <p className="small muted">Backup of the database made first: <code>{n.backup}</code></p>}
        </>
      )}
      {n.failed.length > 0 && (
        <p className="small warn-text">
          Not moved (they keep their folders and are tried again at the next start):{" "}
          {n.failed.map((f) => `${f.name}: ${f.problem}`).join("; ")}
        </p>
      )}
      <button onClick={seen}>OK</button>
    </div>
  );
}
