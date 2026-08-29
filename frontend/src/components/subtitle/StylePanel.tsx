import { Palette } from "lucide-react";
import { Field, Select, Input } from "@/components/ui";
import { FONT_OPTIONS } from "@/lib/subtitleStyle";
import type { SubtitleStyle } from "@/lib/api/types";

export function StylePanel({
  style,
  onChange,
}: {
  style: SubtitleStyle;
  onChange: (patch: Partial<SubtitleStyle>) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
        <Palette size={16} />
        ظاهر زیرنویس
      </div>

      <Field label="فونت">
        <Select value={style.font_family} onChange={(e) => onChange({ font_family: e.target.value })}>
          {FONT_OPTIONS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </Select>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="اندازه فونت">
          <Input
            type="number"
            min={8}
            max={200}
            value={style.font_size}
            onChange={(e) => onChange({ font_size: Number(e.target.value) })}
          />
        </Field>
        <Field label="ضخامت خط دور">
          <Input
            type="number"
            min={0}
            max={20}
            step={0.5}
            value={style.outline_width}
            onChange={(e) => onChange({ outline_width: Number(e.target.value) })}
          />
        </Field>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onChange({ bold: !style.bold })}
          className={toggleClass(style.bold)}
        >
          B
        </button>
        <button
          onClick={() => onChange({ italic: !style.italic })}
          className={toggleClass(style.italic) + " italic"}
        >
          I
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <ColorField label="رنگ متن" value={style.text_color} onChange={(v) => onChange({ text_color: v })} />
        <ColorField label="رنگ پس‌زمینه" value={style.background_color} onChange={(v) => onChange({ background_color: v })} />
      </div>

      <Field label={`شفافیت پس‌زمینه (${Math.round(style.background_opacity * 100)}٪)`}>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={style.background_opacity}
          onChange={(e) => onChange({ background_opacity: Number(e.target.value) })}
          className="w-full accent-brand-600"
        />
      </Field>

      <ColorField label="رنگ خط دور" value={style.outline_color} onChange={(v) => onChange({ outline_color: v })} />

      <Field label="موقعیت عمودی">
        <div className="flex gap-2">
          {(["top", "middle", "bottom"] as const).map((pos) => (
            <button
              key={pos}
              onClick={() => onChange({ position: pos })}
              className={segmentClass(style.position === pos)}
            >
              {{ top: "بالا", middle: "وسط", bottom: "پایین" }[pos]}
            </button>
          ))}
        </div>
      </Field>

      <Field label="چینش افقی">
        <div className="flex gap-2">
          {(["right", "center", "left"] as const).map((align) => (
            <button
              key={align}
              onClick={() => onChange({ alignment: align })}
              className={segmentClass(style.alignment === align)}
            >
              {{ right: "راست", center: "وسط", left: "چپ" }[align]}
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="حاشیه عمودی">
          <Input
            type="number"
            min={0}
            value={style.margin_vertical}
            onChange={(e) => onChange({ margin_vertical: Number(e.target.value) })}
          />
        </Field>
        <Field label="حاشیه افقی">
          <Input
            type="number"
            min={0}
            value={style.margin_horizontal}
            onChange={(e) => onChange({ margin_horizontal: Number(e.target.value) })}
          />
        </Field>
      </div>
    </div>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-9 shrink-0 cursor-pointer rounded-lg border border-slate-300 dark:border-slate-700"
        />
        <Input ltr value={value} onChange={(e) => onChange(e.target.value)} className="flex-1" />
      </div>
    </Field>
  );
}

function toggleClass(active: boolean) {
  return (
    "flex h-9 w-9 items-center justify-center rounded-lg border text-sm font-bold transition-colors " +
    (active
      ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
      : "border-slate-200 text-slate-500 hover:border-slate-300 dark:border-slate-700 dark:text-slate-400")
  );
}

function segmentClass(active: boolean) {
  return (
    "flex-1 rounded-lg border py-1.5 text-xs font-medium transition-colors " +
    (active
      ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
      : "border-slate-200 text-slate-500 hover:border-slate-300 dark:border-slate-700 dark:text-slate-400")
  );
}
