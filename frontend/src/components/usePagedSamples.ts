// Loads samples 200 at a time ("Show more" loads the next 200), and again from the start
// whenever `version` changes (after every action). `first`: how many to load at the start (at least
// one page), to come back to a letter further down the list.
import { useCallback, useEffect, useState } from "react";
import { SamplePage, Sample } from "../api";

export const PAGE = 200;

export function usePagedSamples(load: (offset: number, limit: number) => Promise<SamplePage>, version: number, first = PAGE) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [total, setTotal] = useState(0);
  const [shown, setShown] = useState(() => Math.max(PAGE, Math.ceil(first / PAGE) * PAGE));
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const pages = Array.from({ length: Math.ceil(shown / PAGE) }, (_, i) => load(i * PAGE, PAGE));
    Promise.all(pages).then(
      (rs) => {
        if (!live) return;
        setSamples(rs.flatMap((r) => r.samples));
        setTotal(rs[0]?.total ?? 0);
        setLoading(false);
      },
      (e) => live && (setError(e), setLoading(false)),
    );
    return () => {
      live = false;
    };
  }, [load, version, shown]);

  const more = useCallback(() => setShown((n) => n + PAGE), []);
  return { samples, total, more, error, loading };
}
