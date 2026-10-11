// One line of a page, cropped from the page image, with boxes on it (letters, aksharas): the "Line by line"
// view of Read Book → Text. Boxes are in page pixels; the crop adds a small margin around the line.
import { PageInfo } from "../api";

export interface CropMark {
  key: string | number;
  box: [number, number, number, number];
  className?: string; // "uncertain", "selected"
  title?: string;
  onClick?: () => void;
}

type Box = [number, number, number, number];
const pct = (v: number, of: number) => `${(100 * v) / of}%`;

/** The part of the page shown for a line: its box with a small margin. */
export function cropOf(page: PageInfo, box: Box): Box {
  const pad = Math.max(4, Math.round(box[3] * 0.12));
  const x = Math.max(0, box[0] - pad);
  const y = Math.max(0, box[1] - pad);
  return [x, y, Math.min(page.width - x, box[2] + 2 * pad), Math.min(page.height - y, box[3] + 2 * pad)];
}

export default function LineCrop({ page, box, marks = [] }: { page: PageInfo; box: Box; marks?: CropMark[] }) {
  const [x, y, w, h] = cropOf(page, box);
  return (
    <div className="line-crop" style={{ aspectRatio: `${w} / ${h}` }} aria-label="Line on the page">
      <img src={page.image} alt="" style={{ width: pct(page.width, w), left: pct(-x, w), top: pct(-y, h) }} />
      {marks.map((m) => (
        <span
          key={m.key}
          className={`text-box${m.className ? ` ${m.className}` : ""}`}
          title={m.title}
          onClick={m.onClick}
          style={{ left: pct(m.box[0] - x, w), top: pct(m.box[1] - y, h), width: pct(m.box[2], w), height: pct(m.box[3], h) }}
        />
      ))}
    </div>
  );
}

/** The box around a set of boxes (a line's letters). */
export function unionBox(boxes: [number, number, number, number][]): [number, number, number, number] | null {
  if (!boxes.length) return null;
  const x0 = Math.min(...boxes.map((b) => b[0]));
  const y0 = Math.min(...boxes.map((b) => b[1]));
  const x1 = Math.max(...boxes.map((b) => b[0] + b[2]));
  const y1 = Math.max(...boxes.map((b) => b[1] + b[3]));
  return [x0, y0, x1 - x0, y1 - y0];
}

export interface AlignedItem {
  key: string | number;
  box: Box; // on the page
  text: string;
  className?: string;
  onClick?: () => void;
}

/** A line's text under its cropped image, each akshara at its own place: what is highlighted in the text sits
 *  straight below the same letter on the page. The font follows the width of the letters. */
export function AlignedText({ page, box, items }: { page: PageInfo; box: Box; items: AlignedItem[] }) {
  const [x, , w] = cropOf(page, box);
  const widths = items.map((i) => i.box[2]).sort((a, b) => a - b);
  const typical = widths.length ? widths[Math.floor(widths.length / 2)] : w / 20;
  const size = Math.max(1.2, Math.min(9, ((100 * typical) / w) * 0.8)); // in % of the strip's width
  return (
    <div className="aligned-wrap" aria-label="Text under the line">
      <div className="aligned-text" style={{ ["--fs" as string]: `${size}cqw` }}>
        {items.map((i) => (
          <span key={i.key} className={`text-letter aligned-akshara${i.className ? ` ${i.className}` : ""}`} onClick={i.onClick}
            style={{ left: pct(i.box[0] - x, w), width: pct(i.box[2], w) }}>
            {i.text}
          </span>
        ))}
      </div>
    </div>
  );
}
