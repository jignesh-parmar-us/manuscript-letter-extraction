// Follows a background job (capture, add pages, cut a page again) until it ends.
// The backend is asked for the job's progress once a second.
import { useEffect, useState } from "react";
import { api, Job } from "../api";

export function useJob(initial: Job | null, onEnd: (job: Job) => void): [Job | null, (job: Job | null) => void] {
  const [job, setJob] = useState<Job | null>(initial);
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await api.job(job.id);
        setJob(next);
        if (next.status !== "running") onEnd(next);
      } catch {
        setJob({ ...job }); // try again in a second
      }
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [job, onEnd]);
  return [job, setJob];
}
