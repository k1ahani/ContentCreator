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
 *
 * A page component never talks to `/api/jobs/*` or `/api/events` directly.
 */

import { useCallback, useRef, useState } from "react";
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

export function useJobRunner(onDone?: (job: Job) => void) {
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
    [onDone, queryClient],
  );

  useJobEvents(jobIdRef.current, handleEvent);

  const run = useCallback(
    async (submit: () => Promise<{ job: Job; message: string }>) => {
      setState({ ...initialState, status: "queued" });
      try {
        const response = await submit();
        jobIdRef.current = response.job.id;
        setState((prev) => ({ ...prev, job: response.job, status: "queued" }));
        return response.job;
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "خطای غیرمنتظره‌ای رخ داد.";
        const hint = err instanceof ApiError ? err.hint : undefined;
        setState((prev) => ({ ...prev, status: "failed", error: message, errorHint: hint }));
        throw err;
      }
    },
    [],
  );

  const cancel = useCallback(async () => {
    if (!jobIdRef.current) return;
    await jobsApi.cancel(jobIdRef.current);
  }, []);

  const reset = useCallback(() => {
    jobIdRef.current = undefined;
    setState(initialState);
  }, []);

  return { ...state, run, cancel, reset, isActive: state.status === "queued" || state.status === "running" };
}
