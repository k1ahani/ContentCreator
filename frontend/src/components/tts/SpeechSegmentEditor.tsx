/**
 * Structured speech-script editor.
 *
 * Requirement 23: pauses are not textual markers inside prose, they are
 * discrete, reorderable elements the user places between text blocks. This
 * component owns exactly that list; `SpeechPage` owns voice/rate/pitch and
 * submission.
 *
 * Reordering is native HTML5 drag-and-drop rather than a library, since the
 * list is small (a handful of segments) and the interaction is simple - the
 * same reasoning the subtitle timeline's own mouse-based dragging follows for
 * not reaching for a dependency.
 *
 * Both "insert a new segment" and "drop a dragged segment" target the same
 * *gaps* between rows (`InsertGap`, N+1 of them for N segments: before the
 * first, between every pair, after the last) rather than the rows
 * themselves. Targeting rows is ambiguous - "dropped on row i" could
 * reasonably mean "before row i" or "after row i", and whichever one is
 * picked, it can never express "move this to the very end" when the target
 * is the last row. A gap has no such ambiguity: gap 0 is above everything,
 * gap N is below everything, and gap i is unambiguously between segment i-1
 * and segment i.
 */

import { useState } from "react";
import { GripVertical, Pause, Plus, Trash2, Type } from "lucide-react";
import clsx from "clsx";
import { Textarea, Input } from "@/components/ui";

export interface EditorSegment {
  id: string;
  kind: "text" | "pause";
  text?: string;
  seconds?: number;
}

export function SpeechSegmentEditor({
  segments,
  onChange,
}: {
  segments: EditorSegment[];
  onChange: (segments: EditorSegment[]) => void;
}) {
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dragOverGap, setDragOverGap] = useState<number | null>(null);

  const update = (id: string, patch: Partial<EditorSegment>) =>
    onChange(segments.map((s) => (s.id === id ? { ...s, ...patch } : s)));

  const remove = (id: string) => onChange(segments.filter((s) => s.id !== id));

  /** `gapIndex` follows the same numbering described above: 0..segments.length. */
  const insertAt = (gapIndex: number, kind: "text" | "pause") => {
    const segment: EditorSegment =
      kind === "text"
        ? { id: crypto.randomUUID(), kind: "text", text: "" }
        : { id: crypto.randomUUID(), kind: "pause", seconds: 1 };
    const next = [...segments];
    next.splice(gapIndex, 0, segment);
    onChange(next);
  };

  const moveToGap = (gapIndex: number) => {
    if (!draggedId) return;
    const fromIndex = segments.findIndex((s) => s.id === draggedId);
    if (fromIndex === -1) return;

    const next = [...segments];
    const [moved] = next.splice(fromIndex, 1);
    // Removing the dragged item shifts every later index down by one; a gap
    // that was originally past the dragged item's position needs the same
    // adjustment so it still lands where the user actually dropped it.
    const adjusted = gapIndex > fromIndex ? gapIndex - 1 : gapIndex;
    next.splice(adjusted, 0, moved);
    onChange(next);
  };

  const endDrag = () => {
    setDraggedId(null);
    setDragOverGap(null);
  };

  return (
    <div className="space-y-0.5">
      <InsertGap
        gapIndex={0}
        dragActive={draggedId !== null}
        isDragOver={dragOverGap === 0}
        onDragEnter={() => setDragOverGap(0)}
        onDrop={() => {
          moveToGap(0);
          endDrag();
        }}
        onInsertText={() => insertAt(0, "text")}
        onInsertPause={() => insertAt(0, "pause")}
      />

      {segments.map((segment, index) => (
        <div key={segment.id}>
          <div
            className={clsx(
              "flex items-start gap-2 rounded-xl border p-3 transition-colors",
              draggedId === segment.id
                ? "border-brand-300 bg-brand-50/50 opacity-50 dark:border-brand-800 dark:bg-brand-950/20"
                : "border-slate-200 dark:border-slate-800",
            )}
          >
            <div
              draggable
              onDragStart={(e) => {
                setDraggedId(segment.id);
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", segment.id);
              }}
              onDragEnd={endDrag}
              className="cursor-grab pt-1 text-slate-300 hover:text-slate-500 active:cursor-grabbing dark:text-slate-600 dark:hover:text-slate-400"
              title="برای جابه‌جایی بکشید"
            >
              <GripVertical size={16} />
            </div>

            {segment.kind === "text" ? (
              <div className="flex flex-1 items-start gap-2">
                <Type size={16} className="mt-2.5 shrink-0 text-slate-400" />
                <Textarea
                  value={segment.text ?? ""}
                  onChange={(e) => update(segment.id, { text: e.target.value })}
                  rows={2}
                  placeholder="متن گفتار..."
                  className="flex-1"
                />
              </div>
            ) : (
              <div className="flex flex-1 items-center gap-3 py-1.5">
                <Pause size={16} className="shrink-0 text-slate-400" />
                <span className="text-sm text-slate-500 dark:text-slate-400">مکث به مدت</span>
                <Input
                  ltr
                  type="number"
                  min={0.1}
                  max={30}
                  step={0.1}
                  value={segment.seconds ?? 1}
                  onChange={(e) => update(segment.id, { seconds: Number(e.target.value) })}
                  className="w-24"
                />
                <span className="text-sm text-slate-500 dark:text-slate-400">ثانیه</span>
              </div>
            )}

            <button
              onClick={() => remove(segment.id)}
              className="mt-1.5 shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50"
            >
              <Trash2 size={14} />
            </button>
          </div>

          <InsertGap
            gapIndex={index + 1}
            dragActive={draggedId !== null}
            isDragOver={dragOverGap === index + 1}
            onDragEnter={() => setDragOverGap(index + 1)}
            onDrop={() => {
              moveToGap(index + 1);
              endDrag();
            }}
            onInsertText={() => insertAt(index + 1, "text")}
            onInsertPause={() => insertAt(index + 1, "pause")}
          />
        </div>
      ))}
    </div>
  );
}

/**
 * The gap between two segments (or before the first / after the last).
 * Always a drop target while a drag is in progress; always an "insert here"
 * control on hover regardless of dragging.
 */
function InsertGap({
  gapIndex,
  dragActive,
  isDragOver,
  onDragEnter,
  onDrop,
  onInsertText,
  onInsertPause,
}: {
  gapIndex: number;
  dragActive: boolean;
  isDragOver: boolean;
  onDragEnter: () => void;
  onDrop: () => void;
  onInsertText: () => void;
  onInsertPause: () => void;
}) {
  void gapIndex; // kept in the props list for readability at call sites
  return (
    <div
      className="group/gap relative flex items-center justify-center transition-all"
      style={{ height: dragActive ? (isDragOver ? "2.5rem" : "1rem") : "0.75rem" }}
      onDragOver={(e) => {
        if (!dragActive) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (!isDragOver) onDragEnter();
      }}
      onDrop={(e) => {
        if (!dragActive) return;
        e.preventDefault();
        onDrop();
      }}
    >
      <div
        className={clsx(
          "absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full transition-colors",
          isDragOver
            ? "bg-brand-500"
            : dragActive
              ? "bg-slate-200 dark:bg-slate-700"
              : "bg-transparent group-hover/gap:bg-slate-200 dark:group-hover/gap:bg-slate-700",
        )}
      />
      {!dragActive && (
        <div className="relative z-10 flex gap-1 opacity-0 transition-opacity group-hover/gap:opacity-100">
          <button
            onClick={onInsertText}
            title="افزودن متن در این نقطه"
            className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600 shadow-sm hover:border-brand-400 hover:text-brand-600 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300"
          >
            <Plus size={10} />
            <Type size={10} />
          </button>
          <button
            onClick={onInsertPause}
            title="افزودن مکث در این نقطه"
            className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600 shadow-sm hover:border-brand-400 hover:text-brand-600 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300"
          >
            <Plus size={10} />
            <Pause size={10} />
          </button>
        </div>
      )}
    </div>
  );
}
