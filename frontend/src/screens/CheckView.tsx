// Review groups → Check these (C14): letters the active letter reader is sure belong to another label
// than their group's, read by a reader that did not learn from their page. Most are mistakes in the
// groups (a થા in the યા group); some are the reader's. "Move to …" moves the letter to the group with the
// reader's label (one undoable action); "It is right" marks it as no mix-up for its group's label (kept in
// the library: it leaves this list and the highlights in its group).
import { useCallback, useEffect, useState } from "react";
import { api, CheckItem } from "../api";
import ErrorBox from "../components/ErrorBox";
import { go } from "../route";
import { ReviewContext } from "./Review";

function hiddenKey(readerId: number | null) {
  return `check-right-${readerId}`;
}
/** Letters hidden with "It is right" before it was kept in the library (this browser only), once. */
function takeOldHidden(readerId: number | null): number[] {
  try {
    const ids = JSON.parse(localStorage.getItem(hiddenKey(readerId)) ?? "[]");
    localStorage.removeItem(hiddenKey(readerId));
    return Array.isArray(ids) ? ids : [];
  } catch {
    return [];
  }
}

export default function CheckView({ ctx, readerId }: { ctx: ReviewContext; readerId: number | null }) {
  const [items, setItems] = useState<CheckItem[] | null>(null);
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    api.checkThese(ctx.bookId).then(setItems, setError);
  }, [ctx.bookId]);
  useEffect(load, [load, ctx.version]);
  useEffect(() => {
    const old = takeOldHidden(readerId);
    if (old.length) api.confirmSamples(ctx.bookId, old).then(() => ctx.refresh?.(), setError);
  }, [readerId, ctx.bookId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function right(id: number) {
    setHidden(new Set(hidden).add(id));
    try {
      await api.confirmSamples(ctx.bookId, [id]);
      ctx.refresh?.();
    } catch (e) {
      setError(e);
    }
  }

  const shown = (items ?? []).filter((c) => !hidden.has(c.sample_id));
  return (
    <div className="check-view">
      <h2>
        Check these <span className="muted">({shown.length})</span>
      </h2>
      <p className="small muted">
        Letters your letter checker is sure belong to another letter than their group's (read by a reader that did not learn
        from their page). Most are letters in the wrong group; some are the reader's mistakes. Train the reader again after
        fixing them.
      </p>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {!readerId ? (
        <p className="muted">This book has no letter checker yet: train one in Training Data → Letter checker.</p>
      ) : items === null ? (
        <p className="muted">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="muted">Nothing to check.</p>
      ) : (
        <div className="check-list" aria-label="Letters to check">
          {shown.map((c) => (
            <div key={c.sample_id} className="check-item">
              <img src={c.sample.image} alt={`letter ${c.sample_id}`} />
              <div className="small">
                in <strong>{c.label_guj}</strong> ({c.group_code}) · reads <strong>{c.read_guj}</strong>{" "}
                <span className="muted">({Math.round(c.prob * 100)}%)</span>
                {c.locked && <span className="muted"> · 🔒 locked</span>}
              </div>
              <div className="row small">
                <button
                  className="primary"
                  disabled={c.locked}
                  onClick={() => ctx.act(() => api.labelSamples(ctx.bookId, [c.sample_id], c.read))}
                  title={
                    c.locked
                      ? `${c.group_code} is locked: unlock it to move the letter`
                      : `Move this letter to the ${c.read_guj} group (or a new group labelled ${c.read_guj})`
                  }
                >
                  Move to {c.read_guj}
                </button>
                <button onClick={() => right(c.sample_id)} title="The letter is in the right group: no longer shown as a possible mix-up (here and in its group)">
                  It is right
                </button>
                <button className="link" onClick={() => go(`/books/${ctx.bookId}/review/${c.group_id}`)}>
                  Open group
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
