// A grid of letter samples. Click to select (see selection.ts); drag a sample (with the other
// selected ones) onto a group or "Unsure" in the side list (see screens/Review.tsx).
import { useDraggable } from "@dnd-kit/core";
import { MouseEvent } from "react";
import { Sample } from "../api";

interface Props {
  samples: Sample[];
  selected: Set<number>;
  onClick: (id: number, e: MouseEvent) => void;
  onAccept?: (sample: Sample) => void; // accept the suggested group (unsure samples)
}

export default function SampleGrid({ samples, selected, onClick, onAccept }: Props) {
  if (samples.length === 0) return <p className="muted">No samples.</p>;
  return (
    <div className="grid" role="listbox" aria-multiselectable="true" aria-label="Samples">
      {samples.map((s) => (
        <Tile key={s.id} sample={s} selected={selected.has(s.id)} onClick={onClick} onAccept={onAccept} />
      ))}
    </div>
  );
}

function Tile(props: {
  sample: Sample;
  selected: boolean;
  onClick: Props["onClick"];
  onAccept?: Props["onAccept"];
}) {
  const { sample: s, selected } = props;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `sample-${s.id}` });
  const where = s.page_id ? `line ${s.line}, letter ${s.pos}` : "uploaded";
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      role="option"
      aria-selected={selected}
      className={`tile ink-${s.ink}${selected ? " selected" : ""}${isDragging ? " dragging" : ""}`}
      title={`${where}${s.distance !== null ? ` · distance ${s.distance}` : ""}${s.rules ? ` · ${s.rules}` : ""}`}
      onClick={(e) => props.onClick(s.id, e)}
    >
      <img src={s.image} alt={`sample ${s.id}`} loading="lazy" draggable={false} />
      {s.suggestion && (
        <button
          className="suggestion"
          title={`Suggested: ${s.suggestion.code}, distance ${s.suggestion.distance}. Click to accept.`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            props.onAccept?.(s);
          }}
        >
          → {s.suggestion.label_guj || s.suggestion.code}
        </button>
      )}
    </div>
  );
}
