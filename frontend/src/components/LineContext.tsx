// The one selected letter on its line, with four letters on each side (the backend draws the
// strip from the page, the letter outlined), and a button to open it on its page.
import { Sample } from "../api";

export default function LineContext({ sample, version, onOpen }: { sample: Sample | null; version: number; onOpen: (s: Sample) => void }) {
  if (!sample?.context) return null;
  return (
    <div className="line-context row" aria-label="The letter on its line">
      {/* the version makes the strip load again after a change to the line */}
      <img src={`${sample.context}&v=${version}`} alt={`letter ${sample.id} with its neighbours`} />
      <span className="small muted">
        {sample.page_file} · line {sample.line}
      </span>
      <button onClick={() => onOpen(sample)}>Open on its page</button>
    </div>
  );
}
