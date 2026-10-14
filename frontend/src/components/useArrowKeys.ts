// The arrow keys in a grid of samples (SampleGrid): ← → ↑ ↓ select the next sample, Shift+arrow extends the
// selection (see selection.ts). The tiles' places are read from the screen, since they wrap at the window's width.
import { useEffect } from "react";
import { isTyping } from "../screens/Review";
import { arrowTarget, ARROWS, Box, cursorOf, moveTo, Selection } from "./selection";

const tile = (id: number) => document.querySelector<HTMLElement>(`[data-sample="${id}"]`);

export function useArrowKeys(order: number[], selection: Selection, setSelection: (s: Selection) => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const arrow = ARROWS[e.key];
      if (!arrow || isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || !order.length) return;
      e.preventDefault(); // the page does not scroll by itself: the chosen sample is scrolled into view
      const boxes: Box[] = order.map((id) => tile(id)?.getBoundingClientRect() ?? { left: 0, top: 0, width: 0, height: 0 });
      const to = arrowTarget(order, boxes, cursorOf(selection, order), arrow);
      if (to === null) return;
      setSelection(moveTo(selection, order, to, e.shiftKey));
      tile(to)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [order, selection, setSelection]);
}
