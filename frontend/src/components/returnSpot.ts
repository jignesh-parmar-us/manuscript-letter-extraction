// Going from a letter of the Review tab to its page and back again.
// Double-click on a letter (openOnPage) remembers where it was: the address (group or Unsure), the
// letter, its neighbours in the list and how many letters were loaded. The Pages tab then shows
// "← Back to …" (backTo) until the user goes back (goBack) or opens the Review tab another way
// (forgetSpot). Back in the Review tab, the view (useComeBack) loads as many letters as before,
// selects the letter and scrolls to it, or marks its neighbour if the letter has left the list.
// Kept in memory only: a reload starts afresh.
import { useEffect, useRef, useState } from "react";
import { Sample } from "../api";
import { go } from "../route";

export interface ReturnSpot {
  bookId: number;
  hash: string; // where to go back to
  label: string; // for the button: "ને (g0002)", "Unsure"
  sampleId: number;
  next: number | null; // the letters after and before it in the list, in case it has left
  prev: number | null;
  shown: number; // letters loaded in the list
}

let spot: ReturnSpot | null = null;
let arriving: ReturnSpot | null = null;

export function openOnPage(bookId: number, sample: Sample, list: Sample[], label: string): void {
  const i = list.findIndex((s) => s.id === sample.id);
  spot = {
    bookId,
    hash: window.location.hash,
    label,
    sampleId: sample.id,
    next: list[i + 1]?.id ?? null,
    prev: i > 0 ? list[i - 1].id : null,
    shown: list.length,
  };
  go(`/books/${bookId}/pages/${sample.page_id}/${sample.id}`);
}

/** The spot the Pages tab of this book can go back to. */
export function backTo(bookId: number): ReturnSpot | null {
  return spot && spot.bookId === bookId ? spot : null;
}

export function goBack(): void {
  if (!spot) return;
  arriving = spot;
  spot = null;
  go(arriving.hash);
}

/** The Review tab was opened without "Back": the Pages tab no longer offers it. */
export function forgetSpot(): void {
  spot = null;
}

/** The spot being returned to, if it is this address (kept until the view has used it). */
function arrivalHere(): ReturnSpot | null {
  return arriving && arriving.hash === window.location.hash ? arriving : null;
}

/**
 * In a list of letters (a group, Unsure): `first` is how many to load at the start. Once loaded,
 * the letter come back to is selected (onFound) and scrolled into view, with a dashed outline
 * (`marked`); if it has left the list, its neighbour is marked instead and `note` says so.
 */
export function useComeBack() {
  const [spot] = useState(arrivalHere);
  const [marked, setMarked] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const done = useRef(false);

  function arrive(samples: Sample[], loading: boolean, onFound: (id: number) => void) {
    if (!spot || done.current || loading) return;
    done.current = true;
    arriving = null;
    const has = (id: number | null) => id !== null && samples.some((s) => s.id === id);
    const id = has(spot.sampleId) ? spot.sampleId : has(spot.next) ? spot.next : has(spot.prev) ? spot.prev : null;
    if (id === spot.sampleId) onFound(id);
    else
      setNote(
        `The letter you opened is no longer here (moved, split or deleted)${
          id === null ? "." : `; the dashed outline marks the letter ${id === spot.next ? "after" : "before"} it.`
        }`,
      );
    setMarked(id);
    if (id !== null)
      requestAnimationFrame(() =>
        document.querySelector(`[data-sample="${id}"]`)?.scrollIntoView?.({ block: "center" }),
      );
  }

  return {
    first: spot?.shown ?? 0,
    marked,
    note,
    arrive,
    clear: () => {
      setMarked(null);
      setNote("");
    },
  };
}

/** Run `arrive` whenever the list has loaded (it acts once). */
export function useArrive(
  back: ReturnType<typeof useComeBack>,
  samples: Sample[],
  loading: boolean,
  onFound: (id: number) => void,
): void {
  useEffect(() => back.arrive(samples, loading, onFound));
}
