/**
 * Structured speech-script editor.
 *
 * Requirement 23: pauses are not textual markers inside prose, they are
 * discrete, reorderable elements the user places between text blocks. This
 * component owns exactly that list; `SpeechPage` owns voice/rate/pitch and
 * submission.
 */

import { GripVertical, Pause, Plus, Trash2, Type } from "lucide-react";
import { Textarea, Input, Button } from "@/components/ui";

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
  const update = (id: string, patch: Partial<EditorSegment>) =>
    onChange(segments.map((s) => (s.id === id ? { ...s, ...patch } : s)));

  const remove = (id: string) => onChange(segments.filter((s) => s.id !== id));

  const addText = () =>
    onChange([...segments, { id: crypto.randomUUID(), kind: "text", text: "" }]);

  const addPause = () =>
    onChange([...segments, { id: crypto.randomUUID(), kind: "pause", seconds: 1 }]);

  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= segments.length) return;
    const next = [...segments];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <div className="space-y-2.5">
      {segments.map((segment, index) => (
        <div
          key={segment.id}
          className="flex items-start gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800"
        >
          <div className="flex flex-col items-center gap-1 pt-1 text-slate-300 dark:text-slate-600">
            <button onClick={() => move(index, -1)} disabled={index === 0} className="disabled:opacity-30">
              <GripVertical size={14} />
            </button>
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
      ))}

      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={addText}>
          <Plus size={14} />
          افزودن متن
        </Button>
        <Button size="sm" variant="outline" onClick={addPause}>
          <Plus size={14} />
          افزودن مکث
        </Button>
      </div>
    </div>
  );
}
