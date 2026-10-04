// How a book is written (C10): chosen when the book is created, changeable in "Pages & capture".
import { Writing } from "../api";

export default function WritingChoice(props: { value: Writing; onChange: (w: Writing) => void }) {
  return (
    <fieldset className="plain">
      <legend className="small muted">Writing</legend>
      <label className="row small">
        <input
          type="radio"
          name="writing"
          checked={props.value === "handwritten"}
          onChange={() => props.onChange("handwritten")}
        />
        <strong>Handwritten</strong> <span className="muted">label suggestions come from the books already labelled</span>
      </label>
      <label className="row small">
        <input type="radio" name="writing" checked={props.value === "printed"} onChange={() => props.onChange("printed")} />
        <strong>Printed</strong> <span className="muted">Tesseract reads the pages to suggest labels</span>
      </label>
    </fieldset>
  );
}
