/**
 * Subtitle timeline.
 *
 * A horizontally scrollable, zoomable track of cue blocks. Supports:
 * - clicking empty space to seek the video (requirement: "select timeline
 *   position and find corresponding subtitle")
 * - clicking a cue block to select it
 * - dragging a cue's body to move both start and end together
 * - dragging a cue's left/right edge to change just that boundary
 * - zoom via a slider (pixels-per-second)
 *
 * All edits are optimistic in the parent (`SubtitleEditorPage`); this
 * component only reports gesture deltas in seconds - it holds no server state
 * itself.
 */

import { useCallback, useRef, useState } from "react";
import { ZoomIn, ZoomOut } from "lucide-react";
import clsx from "clsx";
import type { SubtitleCue } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";

type DragMode = "move" | "resize-start" | "resize-end";

interface DragState {
  cueId: string;
  mode: DragMode;
  startX: number;
  originalStart: number;
  originalEnd: number;
}

const MIN_PPS = 10;
const MAX_PPS = 400;
const MIN_CUE_DURATION = 0.15;

export function SubtitleTimeline({
  cues,
  duration,
  currentTime,
  selectedCueId,
  onSeek,
  onSelect,
  onCueChange,
}: {
  cues: SubtitleCue[];
  duration: number;
  currentTime: number;
  selectedCueId: string | null;
  onSeek: (time: number) => void;
  onSelect: (cueId: string | null) => void;
  onCueChange: (cueId: string, start: number, end: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [pxPerSecond, setPxPerSecond] = useState(60);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [dragPreview, setDragPreview] = useState<{ start: number; end: number } | null>(null);

  const width = Math.max(duration * pxPerSecond, 800);

  const timeAtClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track) return 0;
      const rect = track.getBoundingClientRect();
      // RTL: the track scrolls right-to-left visually, so x=0 is the *end* of
      // the timeline in an RTL flex context. We force the timeline itself to
      // an LTR coordinate space (see the `dir="ltr"` wrapper below) so time
      // always increases left-to-right regardless of page direction -
      // standard convention for a timeline scrubber.
      const x = clientX - rect.left + track.scrollLeft;
      return Math.max(0, Math.min(duration, x / pxPerSecond));
    },
    [duration, pxPerSecond],
  );

  const handleTrackClick = (e: React.MouseEvent) => {
    if (drag) return;
    if ((e.target as HTMLElement).closest("[data-cue-block]")) return;
    onSeek(timeAtClientX(e.clientX));
    onSelect(null);
  };

  const startDrag = (cue: SubtitleCue, mode: DragMode) => (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect(cue.id);
    setDrag({ cueId: cue.id, mode, startX: e.clientX, originalStart: cue.start, originalEnd: cue.end });
    setDragPreview({ start: cue.start, end: cue.end });

    const handleMove = (moveEvent: MouseEvent) => {
      const deltaSeconds = (moveEvent.clientX - e.clientX) / pxPerSecond;
      setDragPreview((prev) => {
        if (!prev) return prev;
        if (mode === "move") {
          const span = cue.end - cue.start;
          let newStart = cue.start + deltaSeconds;
          newStart = Math.max(0, Math.min(duration - span, newStart));
          return { start: newStart, end: newStart + span };
        }
        if (mode === "resize-start") {
          const newStart = Math.max(0, Math.min(cue.end - MIN_CUE_DURATION, cue.start + deltaSeconds));
          return { start: newStart, end: cue.end };
        }
        const newEnd = Math.min(duration, Math.max(cue.start + MIN_CUE_DURATION, cue.end + deltaSeconds));
        return { start: cue.start, end: newEnd };
      });
    };

    const handleUp = (upEvent: MouseEvent) => {
      document.removeEventListener("mousemove", handleMove);
      document.removeEventListener("mouseup", handleUp);
      const deltaSeconds = (upEvent.clientX - e.clientX) / pxPerSecond;
      let newStart = cue.start;
      let newEnd = cue.end;
      if (mode === "move") {
        const span = cue.end - cue.start;
        newStart = Math.max(0, Math.min(duration - span, cue.start + deltaSeconds));
        newEnd = newStart + span;
      } else if (mode === "resize-start") {
        newStart = Math.max(0, Math.min(cue.end - MIN_CUE_DURATION, cue.start + deltaSeconds));
      } else {
        newEnd = Math.min(duration, Math.max(cue.start + MIN_CUE_DURATION, cue.end + deltaSeconds));
      }
      setDrag(null);
      setDragPreview(null);
      if (Math.abs(newStart - cue.start) > 0.005 || Math.abs(newEnd - cue.end) > 0.005) {
        onCueChange(cue.id, Math.round(newStart * 1000) / 1000, Math.round(newEnd * 1000) / 1000);
      }
    };

    document.addEventListener("mousemove", handleMove);
    document.addEventListener("mouseup", handleUp);
  };

  const rulerMarks: number[] = [];
  const step = pxPerSecond > 150 ? 1 : pxPerSecond > 60 ? 5 : pxPerSecond > 25 ? 10 : 30;
  for (let t = 0; t <= duration; t += step) rulerMarks.push(t);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{cues.length} قطعه زیرنویس</span>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setPxPerSecond((v) => Math.max(MIN_PPS, v / 1.4))}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <ZoomOut size={14} />
          </button>
          <button
            onClick={() => setPxPerSecond((v) => Math.min(MAX_PPS, v * 1.4))}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <ZoomIn size={14} />
          </button>
        </div>
      </div>

      <div dir="ltr" className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
        <div
          ref={trackRef}
          onClick={handleTrackClick}
          className="relative cursor-pointer select-none bg-slate-50 dark:bg-slate-900"
          style={{ width, height: 96 }}
        >
          {/* ruler */}
          <div className="sticky top-0 z-10 h-6 border-b border-slate-200 bg-slate-100 dark:border-slate-800 dark:bg-slate-800/60">
            {rulerMarks.map((t) => (
              <div
                key={t}
                className="absolute top-0 h-full border-l border-slate-300 pl-1 text-[10px] leading-6 text-slate-400 dark:border-slate-700"
                style={{ left: t * pxPerSecond }}
              >
                {formatDuration(t)}
              </div>
            ))}
          </div>

          {/* cue blocks */}
          <div className="relative" style={{ height: 68 }}>
            {cues.map((cue) => {
              const isDragging = drag?.cueId === cue.id;
              const start = isDragging && dragPreview ? dragPreview.start : cue.start;
              const end = isDragging && dragPreview ? dragPreview.end : cue.end;
              const isSelected = selectedCueId === cue.id;

              return (
                <div
                  key={cue.id}
                  data-cue-block
                  onMouseDown={startDrag(cue, "move")}
                  className={clsx(
                    "group absolute top-2 flex h-12 items-center overflow-hidden rounded-lg border px-2 text-xs shadow-sm transition-colors",
                    isSelected
                      ? "border-brand-500 bg-brand-100 dark:border-brand-500 dark:bg-brand-900/50"
                      : "border-slate-300 bg-white hover:border-brand-300 dark:border-slate-700 dark:bg-slate-800",
                  )}
                  style={{ left: start * pxPerSecond, width: Math.max(4, (end - start) * pxPerSecond) }}
                >
                  <div
                    onMouseDown={startDrag(cue, "resize-start")}
                    className="absolute inset-y-0 start-0 z-10 w-1.5 cursor-ew-resize bg-brand-500/0 group-hover:bg-brand-500/40"
                  />
                  <span className="truncate text-slate-700 dark:text-slate-200" dir="rtl">
                    {cue.text || "(خالی)"}
                  </span>
                  <div
                    onMouseDown={startDrag(cue, "resize-end")}
                    className="absolute inset-y-0 end-0 z-10 w-1.5 cursor-ew-resize bg-brand-500/0 group-hover:bg-brand-500/40"
                  />
                </div>
              );
            })}
          </div>

          {/* playhead */}
          <div
            className="pointer-events-none absolute top-0 z-20 h-full w-px bg-red-500"
            style={{ left: currentTime * pxPerSecond }}
          >
            <div className="absolute -top-0.5 -translate-x-1/2 rounded-b bg-red-500 px-1 py-0.5 text-[9px] font-medium text-white">
              ▼
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
