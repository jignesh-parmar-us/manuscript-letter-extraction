// A grid of letter samples. Click to select (see selection.ts); drag a sample (with the other
// selected ones) onto a group or "Unsure" in the side list (see screens/Review.tsx). Hover shows
// where a sample comes from; double-click opens it on its page (onOpen).
// OCR readings (C12): in a group, a sample whose reading differs from `expected` shows it as a badge;
// clicking the badge removes that reading when it is wrong (onRemoveReading), and a green chip on the
// left moves the sample to the group with that label when the reading is right (onMoveToReading). An
// unsure sample shows its reading as a second suggestion (onAcceptReading).
import { useDraggable } from "@dnd-kit/core";
import { MouseEvent } from "react";
import { Sample } from "../api";

interface Props {
  samples: Sample[];
  selected: Set<number>;
  onClick: (id: number, e: MouseEvent) => void;
  onAccept?: (sample: Sample) => void; // accept the suggested group (unsure samples)
  onOpen?: (sample: Sample) => void; // double-click: show the sample on its page
  expected?: string; // the group's reading (Devanagari): samples read otherwise get a badge
  onAcceptReading?: (sample: Sample) => void; // unsure samples: put the sample under its reading's label
  onRemoveReading?: (sample: Sample) => void; // the badge's reading is wrong: remove it
  onMoveToReading?: (sample: Sample) => void; // the badge's reading is right: move it to that label's group
  marked?: number | null; // the letter come back to from its page (a dashed outline)
}

export default function SampleGrid(props: Props) {
  const { samples, selected, onClick, onAccept, onOpen, expected, onAcceptReading, onRemoveReading, onMoveToReading, marked } =
    props;
  if (samples.length === 0) return <p className="muted">No samples.</p>;
  return (
    <div className="grid" role="listbox" aria-multiselectable="true" aria-label="Samples">
      {samples.map((s) => (
        <Tile
          key={s.id}
          sample={s}
          selected={selected.has(s.id)}
          marked={marked === s.id}
          onClick={onClick}
          onAccept={onAccept}
          onOpen={onOpen}
          expected={expected}
          onAcceptReading={onAcceptReading}
          onRemoveReading={onRemoveReading}
          onMoveToReading={onMoveToReading}
        />
      ))}
    </div>
  );
}

function Tile(props: {
  sample: Sample;
  selected: boolean;
  marked: boolean;
  onClick: Props["onClick"];
  onAccept?: Props["onAccept"];
  onOpen?: Props["onOpen"];
  expected?: string;
  onAcceptReading?: Props["onAcceptReading"];
  onRemoveReading?: Props["onRemoveReading"];
  onMoveToReading?: Props["onMoveToReading"];
}) {
  const { sample: s, selected } = props;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `sample-${s.id}` });
  const where = s.page_id ? `${s.page_file ?? "page"} · line ${s.line}, letter ${s.pos}` : "uploaded";
  const open = s.page_id !== null && props.onOpen ? () => props.onOpen!(s) : undefined;
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      role="option"
      aria-selected={selected}
      data-sample={s.id}
      className={`tile ink-${s.ink}${selected ? " selected" : ""}${props.marked ? " marked" : ""}${isDragging ? " dragging" : ""}`}
      title={`${where}${s.distance !== null ? ` · distance ${s.distance}` : ""}${s.rules ? ` · ${s.rules}` : ""}${
        open ? "\nDouble-click to show it on its page" : ""
      }`}
      onClick={(e) => props.onClick(s.id, e)}
      onDoubleClick={open}
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
      {s.reading && props.onAcceptReading && (
        <button
          className="reading-chip"
          title={`Tesseract read ${s.reading.label_guj} (${s.reading.label_dev}, confidence ${Math.round(s.reading.confidence)}). Click to put it under that label.`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            props.onAcceptReading?.(s);
          }}
        >
          {s.reading.label_guj}
        </button>
      )}
      {s.reading && props.onMoveToReading && props.expected !== undefined && s.reading.label_dev !== props.expected && (
        <button
          className="reading-move"
          title={`Read as ${s.reading.label_guj} (${s.reading.label_dev}). Right? Click to move this letter to the ${s.reading.label_guj} group (a new group with that label if there is none).`}
          aria-label={`Move to ${s.reading.label_guj}`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            props.onMoveToReading?.(s);
          }}
        >
          → {s.reading.label_guj}
        </button>
      )}
      {s.reading && !props.onAcceptReading && props.expected !== undefined && s.reading.label_dev !== props.expected &&
        (props.onRemoveReading ? (
          <button
            className="reading-badge removable"
            title={`Read as ${s.reading.label_guj} (${s.reading.label_dev}). Wrong? Click to remove this reading (undo brings it back).`}
            aria-label={`Remove the reading ${s.reading.label_guj}`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              props.onRemoveReading?.(s);
            }}
          >
            {s.reading.label_guj}
            <span className="remove-x" aria-hidden="true">
              ×
            </span>
          </button>
        ) : (
          <span className="reading-badge" title={`Read as ${s.reading.label_guj} (${s.reading.label_dev})`}>
            {s.reading.label_guj}
          </span>
        ))}
    </div>
  );
}
