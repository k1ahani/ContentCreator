/**
 * Job event stream.
 *
 * One `EventSource` is shared for the whole application (opened once in
 * `JobsProvider`), matching the backend: `/api/events` fans one SSE
 * connection out to every job. Components subscribe to a specific job id or
 * to everything, and the browser's native auto-reconnect handles a dropped
 * connection - the backend just resumes publishing to the new one.
 */

import { useEffect, useRef, useSyncExternalStore } from "react";

export interface JobEvent {
  kind: "status" | "progress" | "log" | "done";
  job_id: string;
  status?: string;
  progress?: number | null;
  stage?: string;
  line?: { ts: number; stream: "stdout" | "stderr" | "system"; text: string };
  error?: string;
  error_code?: string;
  output?: Record<string, unknown>;
}

type Listener = (event: JobEvent) => void;

class JobEventBus {
  private source: EventSource | null = null;
  private listeners = new Set<Listener>();
  private connected = false;
  private connectionListeners = new Set<() => void>();

  connect() {
    if (this.source) return;
    this.source = new EventSource("/api/events");

    this.source.addEventListener("ready", () => {
      this.connected = true;
      this.connectionListeners.forEach((fn) => fn());
    });

    this.source.addEventListener("job", (raw: MessageEvent<string>) => {
      try {
        const event = JSON.parse(raw.data) as JobEvent;
        this.listeners.forEach((listener) => listener(event));
      } catch {
        // A malformed frame should never take down the whole console.
      }
    });

    this.source.onerror = () => {
      this.connected = false;
      this.connectionListeners.forEach((fn) => fn());
      // EventSource retries on its own; nothing to do here.
    };
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeConnection(listener: () => void): () => void {
    this.connectionListeners.add(listener);
    return () => this.connectionListeners.delete(listener);
  }

  isConnected() {
    return this.connected;
  }
}

export const jobEventBus = new JobEventBus();

/** Subscribe to every job event whose `job_id` matches `jobId` (or all, if omitted). */
export function useJobEvents(jobId: string | undefined, onEvent: (event: JobEvent) => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    jobEventBus.connect();
    return jobEventBus.subscribe((event) => {
      if (!jobId || event.job_id === jobId) handlerRef.current(event);
    });
  }, [jobId]);
}

/** Whether the SSE connection is currently open, for a small status dot in the header. */
export function useEventConnectionStatus(): boolean {
  return useSyncExternalStore(
    (callback) => jobEventBus.subscribeConnection(callback),
    () => jobEventBus.isConnected(),
  );
}
