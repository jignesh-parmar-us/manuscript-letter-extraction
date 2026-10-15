// Which group statuses a font takes its glyphs from, with how many groups of the book each gives.
import { Source, Status, STATUS_TEXT } from "./api";

const ALL: Status[] = ["labelled", "auto"];

export default function StatusChoice(props: { source?: Source; value: Status[]; onChange: (v: Status[]) => void }) {
  const toggle = (s: Status) =>
    props.onChange(props.value.includes(s) ? props.value.filter((x) => x !== s) : ALL.filter((x) => x === s || props.value.includes(x)));
  const noLabel = props.source?.groups.reviewed ?? 0;
  return (
    <fieldset className="field">
      <span>Groups to use</span>
      {ALL.map((s) => (
        <label key={s}>
          <input type="checkbox" checked={props.value.includes(s)} onChange={() => toggle(s)} />
          {STATUS_TEXT[s]}
          {props.source && <span className="muted"> ({props.source.usable[s]} groups)</span>}
        </label>
      ))}
      {noLabel > 0 && (
        <span className="muted small">
          {noLabel} reviewed {noLabel === 1 ? "group has" : "groups have"} no label and cannot be used.
        </span>
      )}
    </fieldset>
  );
}
