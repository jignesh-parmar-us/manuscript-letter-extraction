// F11: a small drawing pad for a missing letter. The pad shows the font's baseline and headline as guides
// (from the book's measured lines, F3/F8); the pen starts as thick as the book's headline. Saving sends the
// drawing with its baseline row and scale, so the letter sits on the font's baseline at the drawn size.
import { PointerEvent, useEffect, useRef, useState } from "react";

const PPP = 3; // pad pixels per page pixel
const W = 120; // page pixels shown
const H = 120;
const BASE = 92; // the baseline's row, page pixels from the top

export default function DrawPad(props: {
  char: string;
  headline?: { top: number; thickness: number } | null;
  letterHeight?: number;
  onSave: (png: string, baseline: number, ppp: number) => void;
  onClose: () => void;
}) {
  const pad = useRef<HTMLCanvasElement>(null);
  const [erase, setErase] = useState(false);
  const [pen, setPen] = useState(Math.max(2, Math.round((props.headline?.thickness ?? 6) * 0.8)));
  const drawing = useRef<{ x: number; y: number } | null>(null);
  const head = BASE + (props.headline?.top ?? -(props.letterHeight ?? 55));

  useEffect(() => {
    const c = pad.current?.getContext("2d");
    if (c) c.clearRect(0, 0, W * PPP, H * PPP);
  }, []);

  const at = (e: PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W * PPP, y: ((e.clientY - r.top) / r.height) * H * PPP };
  };
  const stroke = (to: { x: number; y: number }) => {
    const c = pad.current?.getContext("2d");
    const from = drawing.current;
    if (!c || !from) return;
    c.globalCompositeOperation = erase ? "destination-out" : "source-over";
    c.strokeStyle = "#000";
    c.lineWidth = pen * PPP;
    c.lineCap = "round";
    c.lineJoin = "round";
    c.beginPath();
    c.moveTo(from.x, from.y);
    c.lineTo(to.x, to.y);
    c.stroke();
    drawing.current = to;
  };

  return (
    <div className="backdrop" onClick={props.onClose}>
      <div className="dialog draw-dialog" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="row between">
          <h2>Draw {props.char}</h2>
          <button className="link" onClick={props.onClose} aria-label="Close">×</button>
        </div>
        <p className="muted small">
          Draw the letter between the lines: the lower line is the baseline, the upper one the top of the book's
          headline. It is marked as drawn by you.
        </p>
        <div className="draw-area" style={{ width: W * PPP, height: H * PPP }}>
          <div className="guide" style={{ top: BASE * PPP }} title="Baseline" />
          <div className="guide head" style={{ top: head * PPP }} title="Headline" />
          <canvas ref={pad} width={W * PPP} height={H * PPP} aria-label="Drawing pad"
                  onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); drawing.current = at(e); stroke(at(e)); }}
                  onPointerMove={(e) => drawing.current && stroke(at(e))}
                  onPointerUp={() => (drawing.current = null)} />
        </div>
        <div className="row">
          <button className={erase ? "" : "primary"} onClick={() => setErase(false)}>Pen</button>
          <button className={erase ? "primary" : ""} onClick={() => setErase(true)}>Eraser</button>
          <label className="small">
            Width <input type="range" min={1} max={20} value={pen} onChange={(e) => setPen(Number(e.target.value))} /> {pen} px
          </label>
          <button onClick={() => pad.current?.getContext("2d")?.clearRect(0, 0, W * PPP, H * PPP)}>Clear</button>
          <button className="primary" onClick={() => pad.current && props.onSave(pad.current.toDataURL("image/png"), BASE * PPP, PPP)}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
