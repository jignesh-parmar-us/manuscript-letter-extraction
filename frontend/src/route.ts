// Screens are chosen by the part of the address after "#": "#/" is the list of books,
// "#/books/3" is book 3, "#/books/3/groups" its groups. No router library is needed.
import { useEffect, useState } from "react";

export function parts(hash: string): string[] {
  return hash.replace(/^#\/?/, "").split("/").filter(Boolean);
}

export function useRoute(): string[] {
  const [route, setRoute] = useState(() => parts(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parts(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function go(path: string): void {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
}
