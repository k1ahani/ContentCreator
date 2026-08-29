/**
 * Model selector.
 *
 * The UI expression of requirement 5: for a given AI task, show the
 * recommended model, explain why in Persian, and let the user override it -
 * remembering nothing here, since persisting the override to Settings is the
 * caller's job (see SettingsPage's "ai.model_by_task").
 *
 * No model id is ever hardcoded: everything renders from
 * `GET /api/ai/recommend`, which is backed by the model registry.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { aiApi } from "@/lib/api/resources";
import type { AITaskType } from "@/lib/api/types";
import { Skeleton } from "@/components/ui";

const tierLabel: Record<string, string> = {
  fast: "سریع",
  balanced: "متعادل",
  powerful: "قدرتمند",
};

export function ModelSelector({
  task,
  value,
  onChange,
  provider = "claude",
}: {
  task: AITaskType;
  value: string | null;
  onChange: (modelId: string) => void;
  provider?: string;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["recommend", task, provider],
    queryFn: () => aiApi.recommend(task, provider),
  });

  const [manualOpen, setManualOpen] = useState(false);

  useEffect(() => {
    if (data && !value) onChange(data.recommended_model);
  }, [data, value, onChange]);

  if (isLoading || !data) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  const selected = data.alternatives.find((m) => m.id === value) ?? data.alternatives[0];
  const isRecommended = selected?.id === data.recommended_model;

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 dark:border-slate-800 dark:bg-slate-800/40">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {isRecommended ? "مدل پیشنهادی" : "مدل انتخابی"}
          </span>
          {isRecommended && (
            <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-medium text-brand-700 dark:bg-brand-900 dark:text-brand-300">
              پیشنهاد سیستم
            </span>
          )}
        </div>
        <button
          onClick={() => setManualOpen((v) => !v)}
          className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400"
        >
          {manualOpen ? "بستن" : "تغییر مدل"}
        </button>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {selected?.display_name ?? data.recommended_model}
        </span>
        {selected && (
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] text-slate-600 dark:bg-slate-700 dark:text-slate-300">
            {tierLabel[selected.tier] ?? selected.tier}
          </span>
        )}
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-slate-600 dark:text-slate-400">
        {isRecommended ? data.reason_fa : selected?.rationale_fa}
      </p>

      {manualOpen && (
        <div className="mt-3 space-y-1.5 border-t border-slate-200 pt-3 dark:border-slate-700">
          {data.alternatives.map((model) => (
            <button
              key={model.id}
              onClick={() => {
                onChange(model.id);
                setManualOpen(false);
              }}
              className={
                "flex w-full items-center justify-between rounded-lg px-3 py-2 text-start text-sm transition-colors " +
                (model.id === value
                  ? "bg-brand-600 text-white"
                  : "hover:bg-slate-100 dark:hover:bg-slate-700/60")
              }
            >
              <span className="flex items-center gap-2">
                {model.display_name}
                {model.id === data.recommended_model && (
                  <span className={model.id === value ? "text-brand-100" : "text-brand-600 dark:text-brand-400"}>
                    ★
                  </span>
                )}
              </span>
              <span className={clsxTier(model.id === value)}>
                سرعت {model.speed}/۵ · کیفیت {model.quality}/۵
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function clsxTier(isSelected: boolean) {
  return "num text-xs " + (isSelected ? "text-brand-100" : "text-slate-500 dark:text-slate-400");
}
