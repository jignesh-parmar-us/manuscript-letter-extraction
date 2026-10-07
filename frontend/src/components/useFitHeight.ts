// Keeps an element (the side bar of Review groups and Pages) within the window: its bottom stays at
// the window's bottom wherever its top is (below the header, or at the top once the page is
// scrolled and it sticks), so its list scrolls by itself and is never partly below the screen.
// On narrow windows the side bar stacks above the page and the style sheet's height applies.
import { RefObject, useLayoutEffect } from "react";

export const NARROW = 860; // the width below which the two columns stack (styles.css)

/** `prop`: "maxHeight" (a side bar: at most to the bottom) or "height" (an area that fills the rest
 *  of the window, such as the Pages tab's page and selection panel). `key` changes when the element
 *  appears or moves (for example when a page has loaded), so it is fitted again. */
export function useFitHeight(
  ref: RefObject<HTMLElement | null>,
  margin = 8,
  prop: "maxHeight" | "height" = "maxHeight",
  key: unknown = null,
): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      if (window.innerWidth <= NARROW && prop === "maxHeight") {
        el.style.maxHeight = "";
        return;
      }
      const top = Math.max(el.getBoundingClientRect().top, margin);
      el.style[prop] = `${Math.max(prop === "height" ? 320 : 200, window.innerHeight - top - margin)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, { passive: true });
    return () => {
      window.removeEventListener("resize", fit);
      window.removeEventListener("scroll", fit);
    };
  }, [ref, margin, prop, key]);
}
