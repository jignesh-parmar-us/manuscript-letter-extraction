// Uploading pages (C21): page images or one PDF, chosen with the file picker and sent one file at a time
// into a dataset's or a book's upload folder (app/library.py, upload_target). A PDF answers with the job that
// turns it into page images.
import { useState } from "react";
import { api, Job, Kind } from "../api";

const IMAGE = /\.(jpe?g|png|tiff?|bmp)$/i;
const PDF = /\.pdf$/i;

/** Why these files cannot be uploaded together, or "" when they can: page images, or one PDF. */
export function filesProblem(files: File[]): string {
  const odd = files.find((f) => !IMAGE.test(f.name) && !PDF.test(f.name));
  if (odd) return `${odd.name} is not a page image (jpg, png, tif, bmp) or a PDF.`;
  const pdfs = files.filter((f) => PDF.test(f.name)).length;
  if (pdfs > 1) return "Choose one PDF at a time.";
  if (pdfs && files.length > 1) return "Choose page images or one PDF, not both.";
  return "";
}

/** What the chosen files are, in a few words. */
export function filesSummary(files: File[]): string {
  if (!files.length) return "";
  if (files.length === 1) return files[0].name;
  return `${files.length} page images`;
}

/** Upload the files in order; `onProgress(done, total, name)` before each. Returns the PDF's job, if any. A failed
 *  file stops the upload: the error says which one, and the ones before it are kept. */
export async function uploadPages(kind: Kind, id: number, files: File[],
  onProgress?: (done: number, total: number, name: string) => void): Promise<Job | null> {
  let job: Job | null = null;
  for (const [i, file] of files.entries()) {
    onProgress?.(i, files.length, file.name);
    try {
      job = (await api.uploadPage(kind, id, file)).job ?? job;
    } catch (e) {
      const why = e instanceof Error ? e.message : String(e);
      throw new Error(i ? `${file.name} was not uploaded (${i} of ${files.length} were): ${why}` : why);
    }
  }
  onProgress?.(files.length, files.length, "");
  return job;
}

/** The file picker: several page images, or one PDF. */
export function PageFilePicker(props: { files: File[]; onChange: (files: File[]) => void; label?: string; disabled?: boolean }) {
  const problem = filesProblem(props.files);
  return (
    <label className="field">
      <span>{props.label ?? "Page images or a PDF"}</span>
      <input
        type="file"
        aria-label={props.label ?? "Page images or a PDF"}
        multiple
        accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.bmp,application/pdf,image/*"
        disabled={props.disabled}
        onChange={(e) => props.onChange([...(e.target.files ?? [])])}
      />
      {props.files.length > 0 && !problem && <span className="small muted">{filesSummary(props.files)}</span>}
      {problem && (
        <span className="small warn-text" role="alert">
          {problem}
        </span>
      )}
    </label>
  );
}

/** Upload more pages into a row whose pages come from uploads (or that has none yet): a picker and a button. */
export function UploadMore(props: { kind: Kind; id: number; disabled?: boolean; onDone: (job: Job | null) => void;
  onError: (e: unknown) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState("");
  const [key, setKey] = useState(0);              // a new key empties the file input after an upload

  async function upload() {
    try {
      const job = await uploadPages(props.kind, props.id, files, (n, total, name) =>
        setProgress(name ? `Uploading ${n + 1} of ${total}: ${name}` : ""));
      setFiles([]);
      setKey((k) => k + 1);
      props.onDone(job);
    } catch (e) {
      props.onError(e);
    } finally {
      setProgress("");
    }
  }

  return (
    <div className="upload-more">
      <PageFilePicker key={key} files={files} onChange={setFiles} label="Upload page images or a PDF"
        disabled={props.disabled || Boolean(progress)} />
      <div className="row">
        <button disabled={props.disabled || Boolean(progress) || !files.length || Boolean(filesProblem(files))}
          onClick={upload}>
          Upload
        </button>
        {progress && <span className="small muted">{progress}</span>}
      </div>
    </div>
  );
}
