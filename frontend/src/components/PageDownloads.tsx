// Downloads shared by the Text views (Read Book → Text): the page images as a PDF, and the text printed
// as a PDF with every book page starting on a new PDF page.
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";

/** The page images (scans, not text) as a PDF: this page, or every page of the book. */
export function PageImagesPdf({ bookId, pageId, nPages }: { bookId: number; pageId: number | null; nPages: number }) {
  return (
    <>
      <span className="small muted">Page images (PDF):</span>
      <a className={`button small${pageId ? "" : " disabled"}`} href={pageId ? api.pageImagesUrl(bookId, pageId) : undefined}
        title="The image of this page as a PDF">
        This page
      </a>
      <a className={`button small${nPages ? "" : " disabled"}`} href={nPages ? api.pageImagesUrl(bookId) : undefined}
        title="The images of every page as one PDF, a page each">
        All {nPages} pages
      </a>
    </>
  );
}

/** The text of some pages, printed (to PDF) by the browser: each page of the book on a new sheet.
 *  Drawn straight in <body>, outside the app's layout, so the page breaks are kept when printing. */
export function PrintPages({ pages, onDone }: { pages: { key: number; title?: string; lines: string[] }[]; onDone: () => void }) {
  useEffect(() => {
    window.addEventListener("afterprint", onDone, { once: true });
    const t = window.setTimeout(() => window.print(), 50); // after the print view is drawn
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("afterprint", onDone);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return createPortal(
    <div className="print-text" lang="gu">
      {pages.map((p) => (
        <section key={p.key}>
          {pages.length > 1 && p.title && <h3>{p.title}</h3>}
          {p.lines.map((l, i) => (
            <p key={i}>{l}</p>
          ))}
        </section>
      ))}
    </div>,
    document.body,
  );
}
