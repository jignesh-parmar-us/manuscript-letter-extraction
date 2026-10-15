// The main page (F1): the font projects, and "New font" (pick a book; the name starts as the book's name).
import { FormEvent, useEffect, useState } from "react";
import { api, deleteMessage, Font, Source, Status, usable } from "./api";
import { useConfirm } from "./Confirm";
import StatusChoice from "./StatusChoice";
import { go } from "./route";

export default function Fonts() {
  const [fonts, setFonts] = useState<Font[] | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dialog, confirm] = useConfirm();

  const load = () =>
    Promise.all([api.fonts(), api.sources()]).then(([f, s]) => {
      setFonts(f);
      setSources(s);
    }, (e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const bookOf = (f: Font) => sources.find((s) => s.id === f.sources[0]);
  const remove = async (f: Font) => {
    if (!(await confirm(deleteMessage(f), "Delete"))) return;
    api.deleteFont(f.id).then(load, (e: Error) => setError(e.message));
  };

  return (
    <>
      {dialog}
      <h1>Fonts</h1>
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)} aria-label="Close">
            ×
          </button>
        </div>
      )}
      {fonts === null ? (
        <p className="muted">Loading…</p>
      ) : fonts.length === 0 ? (
        <p className="muted">No fonts yet. Make the first one below.</p>
      ) : (
        <table className="list">
          <thead>
            <tr>
              <th>Font</th>
              <th>Book</th>
              <th className="num">Groups</th>
              <th>Built</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {fonts.map((f) => (
              <tr key={f.id}>
                <td>
                  <button className="link strong" onClick={() => go(`/fonts/${f.id}`)}>
                    {f.name}
                  </button>
                </td>
                <td>{bookOf(f)?.name ?? `Book ${f.sources[0]} (not in the library)`}</td>
                <td className="num">{usable(bookOf(f), f.statuses)}</td>
                <td className="small">{f.last_build ? new Date(f.last_build).toLocaleString() : "not yet"}</td>
                <td className="actions">
                  <button className="danger" onClick={() => remove(f)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <NewFont sources={sources} onCreated={(f) => go(`/fonts/${f.id}`)} />
    </>
  );
}

function NewFont(props: { sources: Source[]; onCreated: (f: Font) => void }) {
  const [bookId, setBookId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [statuses, setStatuses] = useState<Status[]>(["labelled"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const source = props.sources.find((s) => s.id === bookId);

  const pick = (id: number) => {
    const before = props.sources.find((s) => s.id === bookId);
    if (!name.trim() || name === before?.name) setName(props.sources.find((s) => s.id === id)?.name ?? "");
    setBookId(id);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (bookId === null) return;
    setBusy(true);
    setError(null);
    api.createFont(name, bookId, statuses).then(props.onCreated, (e: Error) => {
      setError(e.message);
      setBusy(false);
    });
  };

  return (
    <form className="card" onSubmit={submit}>
      <h2>New font</h2>
      <label className="field">
        <span>Book</span>
        <select value={bookId ?? ""} onChange={(e) => pick(Number(e.target.value))} required>
          <option value="" disabled>
            Choose a book…
          </option>
          {props.sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.writing})
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Name (shown in Word's font list)</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <StatusChoice source={source} value={statuses} onChange={setStatuses} />
      {error && <p className="error-text">{error}</p>}
      <button className="primary" type="submit" disabled={busy || bookId === null || !name.trim() || !statuses.length}>
        Create font
      </button>
    </form>
  );
}
