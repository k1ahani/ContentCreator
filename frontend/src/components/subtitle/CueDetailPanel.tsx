import { Trash2, Scissors, ArrowDownToLine, Play } from "lucide-react";
import { Field, Input, Textarea, Button } from "@/components/ui";
import type { SubtitleCue } from "@/lib/api/types";

export function CueDetailPanel({
  cue,
  hasNext,
  onTextChange,
  onTimeChange,
  onDelete,
  onSplit,
  onMerge,
  onSeekToStart,
}: {
  cue: SubtitleCue;
  hasNext: boolean;
  onTextChange: (text: string) => void;
  onTimeChange: (start: number, end: number) => void;
  onDelete: () => void;
  onSplit: (atSeconds: number) => void;
  onMerge: () => void;
  onSeekToStart: () => void;
}) {
  const duration = cue.end - cue.start;
  const cps = duration > 0 ? cue.text.length / duration : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">جزئیات قطعه</span>
        <button
          onClick={onSeekToStart}
          className="flex items-center gap-1 text-xs text-brand-600 hover:underline dark:text-brand-400"
        >
          <Play size={12} />
          پرش به این قطعه
        </button>
      </div>

      <Field label="متن زیرنویس">
        <Textarea value={cue.text} onChange={(e) => onTextChange(e.target.value)} rows={4} />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="شروع (ثانیه)">
          <Input
            ltr
            type="number"
            step={0.1}
            min={0}
            value={cue.start}
            onChange={(e) => onTimeChange(Number(e.target.value), cue.end)}
          />
        </Field>
        <Field label="پایان (ثانیه)">
          <Input
            ltr
            type="number"
            step={0.1}
            min={0}
            value={cue.end}
            onChange={(e) => onTimeChange(cue.start, Number(e.target.value))}
          />
        </Field>
      </div>

      <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800/50">
        <span className="text-slate-500 dark:text-slate-400">سرعت خوانش</span>
        <span className={"num font-medium " + (cps > 21 ? "text-amber-600 dark:text-amber-400" : "text-slate-600 dark:text-slate-300")}>
          {cps.toFixed(1)} نویسه/ثانیه
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => onSplit(cue.start + duration / 2)}
          disabled={duration < 0.3}
        >
          <Scissors size={14} />
          تقسیم از وسط
        </Button>
        <Button size="sm" variant="outline" onClick={onMerge} disabled={!hasNext}>
          <ArrowDownToLine size={14} className="rotate-90" />
          ادغام با بعدی
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete}>
          <Trash2 size={14} />
          حذف
        </Button>
      </div>
    </div>
  );
}
