// What the Books and Datasets screens (C21) share: renaming and deleting a row in its list, and the card with
// the library and uploads folders.
import { FormEvent, ReactNode, useState } from "react";
import { api, AppInfo, BookSummary } from "../api";
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

/** The library folder and the uploads folder (where uploaded pages are kept), each changeable. */
export function AppFolders(props: { info: AppInfo | null; onChanged: () => void; onError: (e: unknown) => void }) {
  const [open, setOpen] = useState<"" | "library" | "uploads">("");
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");
  if (!props.info) return null;

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      if (open === "library") {
        const r = await api.chooseLibrary(folder.trim());
        setMessage(r.restart_needed ? "Saved. Close and start the app again to use this library." : "Saved.");
      } else {
        await api.chooseUploads(folder.trim());
        setMessage("Saved. New uploads go there; pages uploaded before stay where they are.");
      }
      props.onChanged();
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
            <button type="submit" disabled={!folder.trim()}>
              Save
            </button>
            <button type="button" onClick={() => setOpen("")}>
              Close
            </button>
          </div>
          {message && <p className="small">{message}</p>}
        </form>
      )}
    </div>
  );
}
