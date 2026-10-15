// Screens are chosen by the part of the address after "#": "#/" is the list of fonts,
// "#/fonts/f0001" is one font (as in the reading app's frontend/src/route.ts).
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
