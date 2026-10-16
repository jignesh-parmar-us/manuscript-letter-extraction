// Datasets screen (C21): pages whose letters are cut, grouped, reviewed and labelled, what books learn from; and
// New dataset: name, writing, then its pages, uploaded (images or a PDF) or copied from a folder into the uploads
// folder. A folder used in place (only read, never copied) is still chosen in Pages & capture.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, AppInfo, BookSummary, localTime, Writing } from "../api";
import WritingChoice from "../components/WritingChoice";
import ErrorBox from "../components/ErrorBox";
import FolderField from "../components/FolderField";
import { AppFolders, useRowEditing } from "../components/RowList";
import { filesProblem, PageFilePicker, uploadPages } from "../components/UploadPages";
import { go } from "../route";

interface Props {
  info: AppInfo | null;
  onLibraryChanged: () => void;
}

export default function Datasets({ info, onLibraryChanged }: Props) {
  const [datasets, setDatasets] = useState<BookSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.datasets().then(setDatasets, setError);
  }, []);
  useEffect(load, [load]);
  const { dialog, nameCell, actions } = useRowEditing(load, setError);

  return (
    <section>
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
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
                <td className="small">
                  {(b.used_by ?? []).length ? (
                    (b.used_by ?? []).map((u, i) => (
                      <span key={u.id}>
                        {i > 0 && ", "}
                        <button className="link" onClick={() => go(`/books/${u.id}`)}>
                          {u.name}
                        </button>
                      </span>
                    ))
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="small">{localTime(b.updated_at)}</td>
                {actions(b)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewDataset info={info} onError={(e) => { setError(e); load(); }} />
      <AppFolders info={info} onChanged={onLibraryChanged} onError={setError} />
    </section>
  );
}

type Source = "upload" | "folder" | "later";

function NewDataset(props: { info: AppInfo | null; onError: (e: unknown) => void }) {
  const [name, setName] = useState("");
  const [writing, setWriting] = useState<Writing>("handwritten");
  const [source, setSource] = useState<Source>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [folder, setFolder] = useState("");
  const [progress, setProgress] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setProgress("Creating the dataset…");
    let made: number | null = null;
    try {
      made = (await api.createDataset(name.trim(), writing)).id;
      if (source === "upload") {
        await uploadPages("dataset", made, files, (n, total, file) => setProgress(`Uploading ${n + 1} of ${total}: ${file}`));
      } else if (source === "folder") {
        await api.copyFolder(made, folder.trim());       // a job, followed in Pages & capture
      }
      go(`/books/${made}/capture`);
    } catch (err) {
      setProgress("");
      props.onError(made === null ? err
        : new Error(`The dataset "${name.trim()}" was made, but its pages were not all added: ${(err as Error).message} ` +
          "Open it to choose its pages in Pages & capture."));
    }
  }

  const busy = Boolean(progress);
  const ready = source === "upload" ? !filesProblem(files) : source === "folder" ? Boolean(folder.trim()) : true;
  return (
    <form className="card" onSubmit={submit}>
      <h2>New dataset</h2>
      <label className="field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="For example: Vachanamrut, part 1" required />
      </label>
      <WritingChoice value={writing} onChange={setWriting} />
      <fieldset className="plain">
        <legend className="small muted">Pages</legend>
        <label className="row small">
          <input type="radio" name="source" checked={source === "upload"} onChange={() => setSource("upload")} />
          <strong>Upload page images or a PDF</strong>
        </label>
        <label className="row small">
          <input type="radio" name="source" checked={source === "folder"} onChange={() => setSource("folder")} />
          <strong>Copy a folder of page images</strong>
        </label>
        <label className="row small">
          <input type="radio" name="source" checked={source === "later"} onChange={() => setSource("later")} />
          <strong>Later</strong> <span className="muted">in Pages & capture (also a folder used where it is)</span>
        </label>
      </fieldset>
      {source === "upload" && <PageFilePicker files={files} onChange={setFiles} disabled={busy} />}
      {source === "folder" && (
        <FolderField label="Folder with the page images" value={folder} onChange={setFolder} info={props.info} />
      )}
      {source !== "later" && (
        <p className="muted small">
          The pages are copied into the uploads folder (a PDF's pages become images); the originals are not touched.
          Then cut them into letters in Pages & capture.
        </p>
      )}
      <div className="row">
        <button className="primary" type="submit" disabled={busy || !name.trim() || !ready}>
          Create dataset
        </button>
        {progress && <span className="small muted">{progress}</span>}
      </div>
    </form>
  );
}
