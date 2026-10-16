// Read Book → Dictionary (C15): the book's language model. When converting, it may change uncertain letters
// to readings that make more likely text; it learns from the book's own labels (its Training Data letters
// in reading order), its proofread lines and the word lists the book uses (imported text files, Gujarati or
// Devanagari). Letters it changed are underlined in the Text view and stay marked uncertain.
import { useCallback, useEffect, useState } from "react";
import { api, Book, BookLanguage, WordListInfo } from "../api";
import { useConfirm } from "../components/Confirm";
import ErrorBox from "../components/ErrorBox";

interface Props {
  book: Book;
  onChanged: () => void;
}

const n = (v: number) => v.toLocaleString();

export default function Dictionary({ book, onChanged }: Props) {
  const [info, setInfo] = useState<BookLanguage | null>(null);
  const [lists, setLists] = useState<WordListInfo[]>([]);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dialog, confirm] = useConfirm();

  const load = useCallback(() => {
    api.bookLanguage(book.id).then(setInfo, setError);
    api.wordLists().then(setLists, setError);
  }, [book.id]);
  useEffect(load, [load, book.settings]);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const enabled = info?.enabled ?? true;
  return (
    <div className="dictionary">
      {dialog}
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="card">
        <h2>Language model</h2>
        <p className="small muted">
          When converting pages, it may change an <strong>uncertain</strong> letter to another reading the readers saw, if
          that makes the line much more like the text it knows. A sure letter is never changed. The letters it changed
          are underlined in the Text view and stay marked uncertain. Convert again after changing what it learns from.
        </p>
        <label className="row">
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={(e) =>
              run(async () => {
                await api.setSettings(book.id, { ...(book.settings ?? {}), language_model: e.target.checked });
                onChanged();
              })
            }
          />
          Use the language model when converting this book
        </label>
        {info && (
          <table className="list compact" aria-label="Learns from">
            <tbody>
              <tr>
                <td>Your labels (the letters of the book's dataset, in reading order)</td>
                <td className="num">{n(info.labels.aksharas)} letters</td>
              </tr>
              <tr>
                <td>Your proofread lines</td>
                <td className="num">
                  {n(info.proofread.lines)} {info.proofread.lines === 1 ? "line" : "lines"} · {n(info.proofread.aksharas)} letters
                </td>
              </tr>
              <tr>
                <td>Word lists this book uses</td>
                <td className="num">
                  {info.lists.length} · {n(info.lists.reduce((a, w) => a + w.aksharas, 0))} letters
                </td>
              </tr>
              <tr>
                <th>All together</th>
                <th className="num">{n(info.aksharas)} letters</th>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Word lists</h2>
        <p className="small muted">
          A UTF-8 text file in Gujarati or Devanagari: running text or one word per line (other characters are left out).
          The more text of the same language and style, the better: for example the full text of the book, or of works
          like it.
        </p>
        <div className="row">
          <input
            className="wordlist-path"
            aria-label="Text file"
            placeholder="/path/to/text.txt"
            value={path}
            onChange={(e) => setPath(e.target.value)}
          />
          <input aria-label="Name" placeholder="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <button
            className="primary"
            disabled={busy || !path.trim()}
            onClick={() =>
              run(async () => {
                await api.importWordList(path.trim(), name.trim(), book.id);
                setPath("");
                setName("");
              })
            }
          >
            Import
          </button>
        </div>
        {lists.length > 0 ? (
          <table className="list" aria-label="Word lists">
            <thead>
              <tr>
                <th>Name</th>
                <th className="num">Lines</th>
                <th className="num">Letters</th>
                <th>This book</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lists.map((w) => (
                <tr key={w.id}>
                  <td>{w.name}</td>
                  <td className="num">{n(w.lines)}</td>
                  <td className="num">{n(w.aksharas)}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Use ${w.name} for this book`}
                      checked={w.books.includes(book.id)}
                      disabled={busy}
                      onChange={(e) => run(() => api.useWordList(w.id, book.id, e.target.checked))}
                    />
                  </td>
                  <td className="actions">
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={async () => {
                        if (await confirm(`Delete the word list ${w.name}? Books that use it stop using it.`, "Delete"))
                          run(() => api.deleteWordList(w.id));
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No word lists yet: the language model learns from your labels and proofread lines.</p>
        )}
      </div>
    </div>
  );
}
