// The Pages tab's page chooser: a dialog with every page of the book, a search box and the number of
// letters on each page, instead of a list down the side of the screen. Type to filter by file name,
// Enter opens the first match, Esc closes. Drawn into <body> like the other dialogs.
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PageInfo } from "../api";

interface Props {
  pages: PageInfo[];
  currentId: number | null;
  onPick: (page: PageInfo) => void;
  onClose: () => void;
}

export default function PagePicker({ pages, currentId, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const current = useRef<HTMLButtonElement>(null);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? pages.filter((p) => p.file.toLowerCase().includes(q)) : pages;
  }, [pages, query]);

  useEffect(() => {
    current.current?.scrollIntoView?.({ block: "center" });
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog page-picker" role="dialog" aria-modal="true" aria-label="Choose a page">
        <div className="row between">
          <h2>Choose a page</h2>
          <button onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <input
          className="page-search"
          aria-label="Search pages"
          placeholder={`Search ${pages.length} pages by name`}
          value={query}
          autoFocus
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && shown.length) onPick(shown[0]);
          }}
        />
        <div className="page-list" role="listbox" aria-label="Pages">
          {shown.map((p) => (
            <button
              key={p.id}
              ref={p.id === currentId ? current : undefined}
              role="option"
              aria-selected={p.id === currentId}
              className={`page-item${p.id === currentId ? " active" : ""}`}
              onClick={() => onPick(p)}
            >
              <span className="page-name">{p.file}</span>
              <span className="muted small">
                {p.samples} letters{p.status !== "OK" ? ` · ${p.status}` : ""}
              </span>
            </button>
          ))}
          {shown.length === 0 && <p className="muted small">No page matches “{query}”.</p>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
