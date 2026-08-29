/**
 * useJobRunner - starts a background job and tracks it live.
 *
 * This is the hook every feature page (audio extraction, transcription, text
 * editing, subtitle generation/render, TTS) builds on. It owns:
 *
 * - submission (calling the `POST .../xxx` endpoint that returns 202 + a job)
 * - live progress/stage via SSE, with a polling fallback so a page still
 *   updates correctly if SSE is unavailable
 * - the accumulated console log lines for the CLI console component
 * - cancellation
 * - surviving navigation away from the page and back (see `persistKey` below)
 *
 * A page component never talks to `/api/jobs/*` or `/api/events` directly.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { jobsApi } from "@/lib/api/resources";
import { useJobEvents, type JobEvent } from "@/lib/api/events";
import type { Job, JobLogLine } from "@/lib/api/types";
import { ApiError } from "@/lib/api/client";

export interface JobRunnerState {
  job: Job | null;
  status: "idle" | "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number | null;
  stage: string;
  logs: JobLogLine[];
  error: string | null;
  errorHint?: string;
}

const initialState: JobRunnerState = {
  job: null,
  status: "idle",
  progress: null,
  stage: "",
  logs: [],
  error: null,
};

// Reading/writing localStorage can throw (private browsing, disabled site
// data); a lost "resume this job" convenience is never worth crashing the
// page over, so every access here is defensive.
function readPersisted(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writePersisted(key: string, jobId: string): void {
  try {
    localStorage.setItem(key, jobId);
  } catch {
    /* ignore */
  }
}
function clearPersisted(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/**
 * @param onDone called once when a job that finished successfully - live or
 *   rehydrated - reaches `completed`. NOT called again for a job that was
 *   already terminal when rehydrated from a previous mount of this hook (the
 *   page would otherwise re-show a "just finished!" toast for a result the
 *   user may have already seen), which is why rehydration marks it as such.
 * @param persistKey when set, an active job's id is remembered under this
 *   key (localStorage) while it runs. If the component unmounts - the user
 *   navigates to another tab - and a *new* instance of this hook mounts later
 *   with the same key (the user comes back), it fetches the job's current
 *   state and persisted logs and resumes live tracking exactly where it left
 *   off, including if the job kept running the whole time. This is what lets
 *   a long transcription or render survive the user browsing elsewhere and
 *   coming back to it. Give each feature page its own key, scoped to the
 *   project (e.g. `` `cca:job:${projectId}:transcribe` ``) so unrelated
 *   pages/projects never resume each other's jobs.
 */
export function useJobRunner(onDone?: (job: Job) => void, persistKey?: string) {
  const [state, setState] = useState<JobRunnerState>(initialState);
  const jobIdRef = useRef<string | undefined>(undefined);
  const queryClient = useQueryClient();

  const handleEvent = useCallback(
    (event: JobEvent) => {
      setState((prev) => {
        if (event.kind === "log" && event.line) {
          return { ...prev, logs: [...prev.logs, event.line] };
        }
        if (event.kind === "progress") {
          return {
            ...prev,
            progress: event.progress ?? prev.progress,
            stage: event.stage ?? prev.stage,
            status: "running",
          };
        }
        if (event.kind === "status" && event.status) {
          return { ...prev, status: event.status as JobRunnerState["status"] };
        }
        if (event.kind === "done") {
          const status = (event.status ?? "completed") as JobRunnerState["status"];
          return {
            ...prev,
            status,
            progress: status === "completed" ? 1 : prev.progress,
            error: event.error ?? null,
          };
        }
        return prev;
      });

      if (event.kind === "done" && jobIdRef.current) {
        if (persistKey) clearPersisted(persistKey);
        // Refetch the authoritative job record (has the full `output`).
        jobsApi.get(jobIdRef.current).then((job) => {
          setState((prev) => ({ ...prev, job }));
          if (job.status === "completed") onDone?.(job);
          // Invalidate list caches that likely changed (assets, documents, jobs).
          queryClient.invalidateQueries({ queryKey: ["assets"] });
          queryClient.invalidateQueries({ queryKey: ["documents"] });
          queryClient.invalidateQueries({ queryKey: ["subtitleTracks"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          queryClient.invalidateQueries({ queryKey: ["project"] });
        });
      }
    },
    [onDone, queryClient, persistKey],
  );

  useJobEvents(jobIdRef.current, handleEvent);

  // Rehydration: on mount, resume tracking whatever job (if any) was left
  // running under this key the last time a page with this hook was open.
  useEffect(() => {
    if (!persistKey) return;
    const storedJobId = readPersisted(persistKey);
    if (!storedJobId) return;

    let cancelled = false;
    Promise.all([jobsApi.get(storedJobId), jobsApi.logs(storedJobId)])
      .then(([job, logsResponse]) => {
        if (cancelled) return;
        const terminal = job.status === "completed" || job.status === "failed" || job.status === "cancelled";
        if (terminal) clearPersisted(persistKey);

        jobIdRef.current = job.id;
        setState({
          job,
          status: job.status,
          progress: job.progress,
          stage: job.stage,
          logs: logsResponse.items,
          error: job.error,
        });
        // Deliberately not calling onDone here - see the jsdoc above.
      })
      .catch(() => {
        // The stored job id no longer resolves (deleted database, expired
        // dev data); drop the stale pointer rather than retrying forever.
        if (!cancelled) clearPersisted(persistKey);
      });

    return () => {
      cancelled = true;
    };
    // Intentionally only on mount / when the key itself changes (switching
    // project or feature) - not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persistKey]);

  const run = useCallback(
    async (submit: () => Promise<{ job: Job; message: string }>) => {
      setState({ ...initialState, status: "queued" });
      try {
        const response = await submit();
        jobIdRef.current = response.job.id;
        if (persistKey) writePersisted(persistKey, response.job.id);
        setState((prev) => ({ ...prev, job: response.job, status: "queued" }));
        return response.job;
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "خطای غیرمنتظره‌ای رخ داد.";
        const hint = err instanceof ApiError ? err.hint : undefined;
        setState((prev) => ({ ...prev, status: "failed", error: message, errorHint: hint }));
        throw err;
      }
    },
    [persistKey],
  );

  const cancel = useCallback(async () => {
    if (!jobIdRef.current) return;
    await jobsApi.cancel(jobIdRef.current);
  }, []);

  const reset = useCallback(() => {
    jobIdRef.current = undefined;
    if (persistKey) clearPersisted(persistKey);
    setState(initialState);
  }, [persistKey]);

  return { ...state, run, cancel, reset, isActive: state.status === "queued" || state.status === "running" };
}
