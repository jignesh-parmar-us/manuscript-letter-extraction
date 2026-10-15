// One font, in tabs: Glyphs (F2, Glyphs.tsx) and Settings (F1: its name, renamed at any time and used from
// the next build on; the group statuses it uses; Delete). Build (F5) and Try it (F6) come here later.
import { FormEvent, useEffect, useState } from "react";
import { api, deleteMessage, Font, Source, Status, usable } from "./api";
import { useConfirm } from "./Confirm";
import Glyphs from "./Glyphs";
import StatusChoice from "./StatusChoice";
import { go } from "./route";

export default function FontView({ fontId, tab }: { fontId: string; tab: string }) {
  const [font, setFont] = useState<Font | null>(null);
  const [source, setSource] = useState<Source | undefined>();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [dialog, confirm] = useConfirm();

  const show = (f: Font) => {
    setFont(f);
    setName(f.name);
  };
  useEffect(() => {
    Promise.all([api.font(fontId), api.sources()]).then(([f, s]) => {
      show(f);
      setSource(s.find((b) => b.id === f.sources[0]));
    }, (e: Error) => setError(e.message));
  }, [fontId]);

  const change = (c: { name?: string; statuses?: Status[] }, message: string) => {
    setError(null);
    api.changeFont(fontId, c).then((f) => {
      show(f);
      setSaved(message);
    }, (e: Error) => setError(e.message));
  };
  const rename = (e: FormEvent) => {
    e.preventDefault();
    change({ name }, "Renamed. The new name is used from the next build on.");
  };
  const remove = async () => {
    if (font && (await confirm(deleteMessage(font), "Delete"))) api.deleteFont(fontId).then(() => go("/"), (e: Error) => setError(e.message));
  };

  return (
    <>
      {dialog}
      <p>
        <button className="link" onClick={() => go("/")}>
          ← Fonts
        </button>
      </p>
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {font && (
        <>
          <h1>{font.name}</h1>
          <p className="muted">
            From {source ? `${source.name} (${source.writing})` : `book ${font.sources[0]}, not in the library`}:{" "}
            {usable(source, font.statuses)} groups can become glyphs.{" "}
            {font.last_build ? `Last built ${new Date(font.last_build).toLocaleString()}.` : "Not built yet."}
          </p>
          <nav className="tabs">
            {[["glyphs", "Glyphs"], ["settings", "Settings"]].map(([t, text]) => (
              <button key={t} className={`tab${tab === t ? " active" : ""}`} onClick={() => go(`/fonts/${fontId}/${t}`)}>
                {text}
              </button>
            ))}
          </nav>
          {tab === "glyphs" && <Glyphs key={font.statuses.join()} fontId={fontId} />}
          {tab === "settings" && (
          <>
          <div className="card">
            <form className="row" onSubmit={rename}>
              <label className="field">
                <span>Name</span>
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </label>
              <button type="submit" disabled={!name.trim() || name === font.name}>
                Rename
              </button>
            </form>
            <StatusChoice
              source={source}
              value={font.statuses}
              onChange={(v) => v.length && change({ statuses: v }, "Saved.")}
            />
            {saved && <p className="muted small">{saved}</p>}
          </div>
          <button className="danger" onClick={remove}>
            Delete font
          </button>
          </>
          )}
        </>
      )}
    </>
  );
}
