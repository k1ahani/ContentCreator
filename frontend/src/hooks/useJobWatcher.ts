/**
 * useJobWatcher - follow an *existing* job's live console.
 *
 * Distinct from `useJobRunner`, which starts a job. This is for the AI
 * console page, where the user picks a job from history (possibly still
 * running) and wants to watch it: persisted logs are loaded once, then new
 * lines stream in over SSE.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { jobsApi } from "@/lib/api/resources";
import { useJobEvents, type JobEvent } from "@/lib/api/events";
import type { Job, JobLogLine } from "@/lib/api/types";

export function useJobWatcher(jobId: string | undefined) {
  const [liveLines, setLiveLines] = useState<JobLogLine[]>([]);
  const [liveJob, setLiveJob] = useState<Job | null>(null);

  const jobQuery = useQuery({
    queryKey: ["jobs", jobId],
    queryFn: () => jobsApi.get(jobId!),
    enabled: Boolean(jobId),
  });
  const logsQuery = useQuery({
    queryKey: ["jobLogs", jobId],
    queryFn: () => jobsApi.logs(jobId!),
    enabled: Boolean(jobId),
  });

  useEffect(() => {
    setLiveLines([]);
    setLiveJob(null);
  }, [jobId]);

  useJobEvents(jobId, (event: JobEvent) => {
    if (event.kind === "log" && event.line) {
      setLiveLines((prev) => [...prev, event.line!]);
    }
    if (event.kind === "done" || event.kind === "status") {
      jobsApi.get(jobId!).then(setLiveJob).catch(() => {});
    }
  });

  const job = liveJob ?? jobQuery.data ?? null;
  const logs = [...(logsQuery.data?.items ?? []), ...liveLines];

  return { job, logs, isLoading: jobQuery.isLoading };
}
