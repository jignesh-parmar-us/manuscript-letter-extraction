// "Export" tab: write the book's dataset for OCR training (FR-9): every sample of each labelled
// letter in its own folder, the lines with their Gujarati text, letters.csv, samples.csv,
// overview.html and summary.txt. Unlabelled samples go to unsure/.
import { FormEvent, useCallback, useState } from "react";
import { api, AppInfo, Book } from "../api";
import ErrorBox from "../components/ErrorBox";
import { useJob } from "../components/useJob";

const IMAGES: { id: string; label: string; help: string }[] = [
  { id: "original", label: "Original", help: "the letter as cut from the page, on its paper" },
  { id: "normalized", label: "Black on white", help: "only the letter's ink, black on white, original size" },
  { id: "fixed64", label: "Black on white, 64 × 64", help: "the same, scaled into 64 × 64 pixels for training" },
];

export default function Export({ book, info }: { book: Book; info: AppInfo | null }) {
  const [image, setImage] = useState(String(book.settings.dataset_image ?? "original"));
  const [where, setWhere] = useState<"book" | "folder">("book");
  const [folder, setFolder] = useState("");
  const [error, setError] = useState<unknown>(null);
  const onEnd = useCallback(() => {}, []);
  const [job, setJob] = useJob(null, onEnd);

  async function start(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      setJob(await api.exportBook(book.id, where === "folder" ? folder.trim() : null, image));
    } catch (err) {
      setError(err);
    }
  }
  async function browse() {
    const { path } = await api.pickFolder();
    if (path) setFolder(path);
  }

  const result = job?.status === "done" ? (job.result as Record<string, unknown>) : null;
  const running = job?.status === "running";

  return (
    <div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <form className="card" onSubmit={start}>
        <p className="small muted">
          {book.labelled} of {book.groups} groups are labelled. Only labelled letters go into the dataset; the other
          samples are exported to <code>unsure/</code>.
        </p>
        <fieldset className="plain">
          <legend className="small muted">Images in the dataset</legend>
          {IMAGES.map((o) => (
            <label key={o.id} className="row small">
              <input type="radio" name="image" value={o.id} checked={image === o.id} onChange={() => setImage(o.id)} />
              <strong>{o.label}</strong> <span className="muted">{o.help}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="plain">
          <legend className="small muted">Where</legend>
          <label className="row small">
            <input type="radio" name="where" checked={where === "book"} onChange={() => setWhere("book")} />
            In the book's folder of the library (a new folder with the date and time)
          </label>
          <label className="row small">
            <input type="radio" name="where" checked={where === "folder"} onChange={() => setWhere("folder")} />
            In another folder (new or empty)
          </label>
          {where === "folder" && (
            <span className="row">
              <input aria-label="Export folder" value={folder} onChange={(e) => setFolder(e.target.value)} required />
              {info?.can_pick_folder && (
                <button type="button" onClick={browse}>
                  Browse…
                </button>
              )}
            </span>
          )}
        </fieldset>
        <button className="primary" type="submit" disabled={running || (where === "folder" && !folder.trim())}>
          Export
        </button>
      </form>

      {job && running && <p className="muted">Exporting… {job.seconds} s</p>}
      {job?.status === "failed" && <p className="error">{job.error}</p>}
      {result && <ExportResult result={result} />}
    </div>
  );
}

function ExportResult({ result }: { result: Record<string, unknown> }) {
  const [error, setError] = useState<unknown>(null);
  const folder = String(result.folder);
  const rows: [string, unknown][] = [
    ["Letters (classes)", result.classes],
    ["Labelled samples", result.labelled_samples],
    ["Classes with few samples", result.few_samples],
    ["Unsure samples", result.unsure],
    ["Pages / lines", `${result.pages} / ${result.lines}`],
    ["Uploaded samples", result.uploaded],
  ];
  const kept = (result.kept_in_devanagari as string[]) ?? [];
  return (
    <div className="card" aria-live="polite">
      <strong>Exported</strong>
      <p className="small">
        <code>{folder}</code>
      </p>
      <table className="list compact">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="num">{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {kept.length > 0 && <p className="small warnings">Kept in Devanagari (no Gujarati form): {kept.join(" ")}</p>}
      <div className="row">
        <button onClick={() => api.openFolder(folder).catch(setError)}>Open the folder</button>
        <span className="muted small">Open overview.html there to see every letter.</span>
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />
    </div>
  );
}
