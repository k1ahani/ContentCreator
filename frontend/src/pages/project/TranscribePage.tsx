/**
 * Feature 2: Audio -> Text.
 *
 * Two real stages, both through the provider architecture (see
 * docs/AI_SYSTEM.md): local Whisper produces timed segments
 * (backend/app/transcription/), then an optional Claude pass refines
 * punctuation and spelling (AITaskType.TRANSCRIPTION_REFINEMENT). The model
 * selector controls stage two only - no LLM accepts audio.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Captions, Play, CheckCircle2, AlertCircle } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { aiApi, assetsApi, jobsApi } from "@/lib/api/resources";
import { ModelSelector } from "@/components/ai/ModelSelector";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, Select, Field, ProgressBar, Badge, EmptyState } from "@/components/ui";
import type { Language } from "@/lib/api/types";

export function TranscribePage() {
  const { projectId } = useProject();
  const [assetId, setAssetId] = useState<string>("");
  const [language, setLanguage] = useState<Language>("fa");
  const [refine, setRefine] = useState(true);
  const [model, setModel] = useState<string | null>(null);

  const { data: audioAssets } = useQuery({
    queryKey: ["assets", projectId, "audio"],
    queryFn: () => assetsApi.list(projectId, "audio"),
  });
  const { data: engines } = useQuery({
    queryKey: ["transcriptionEngines"],
    queryFn: () => aiApi.transcriptionEngines(true),
  });

  // persistKey: transcription is the operation most likely to run long
  // enough that a user wanders off to another tab and comes back - this is
  // what lets them do that without losing sight of progress (or the
  // finished transcript, if it completed while they were away).
  const runner = useJobRunner(undefined, `cca:job:${projectId}:transcribe`);
  const engine = engines?.items[0];

  const start = () => {
    if (!assetId) return;
    runner.run(() =>
      jobsApi.transcribe(projectId, {
        asset_id: assetId,
        language,
        refine,
        ai_model: refine ? model ?? undefined : undefined,
      }),
    );
  };

  const output = runner.job?.output as
    | { text?: string; segment_count?: number; refined?: boolean; refine_error?: string; engine_model?: string }
    | undefined;

  if (audioAssets && audioAssets.items.length === 0) {
    return (
      <EmptyState
        icon={<Captions size={40} />}
        title="ابتدا صدا استخراج کنید"
        description="برای تبدیل گفتار به متن، نیاز به یک فایل صوتی در پروژه دارید."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">تبدیل صدا به متن</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          گفتار موجود در فایل صوتی به‌صورت محلی تشخیص داده و سپس با هوش مصنوعی بازبینی می‌شود
        </p>
      </div>

      {engine && !engine.available && (
        <div className="flex items-start gap-2.5 rounded-xl bg-amber-50 p-3.5 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <div>
            <p>{engine.unavailable_reason}</p>
            {engine.hint && <p className="mt-1 text-xs opacity-80">{engine.hint}</p>}
          </div>
        </div>
      )}

      <Card>
        <CardHeader title="تنظیمات تبدیل" />
        <CardBody className="space-y-4">
          <Field label="فایل صوتی">
            <Select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              <option value="">انتخاب کنید...</option>
              {audioAssets?.items.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.original_filename}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="زبان گفتار">
            <div className="flex gap-2">
              {(["fa", "en"] as const).map((lang) => (
                <button
                  key={lang}
                  onClick={() => setLanguage(lang)}
                  className={
                    "flex-1 rounded-xl border py-2.5 text-sm font-medium transition-colors " +
                    (language === lang
                      ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                      : "border-slate-200 text-slate-600 hover:border-slate-300 dark:border-slate-800 dark:text-slate-400")
                  }
                >
                  {lang === "fa" ? "فارسی" : "English"}
                </button>
              ))}
            </div>
          </Field>

          <label className="flex items-center gap-2.5 text-sm text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={refine}
              onChange={(e) => setRefine(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            بازبینی خودکار متن با هوش مصنوعی (نقطه‌گذاری و اصلاح املا)
          </label>

          {refine && (
            <ModelSelector task="transcription_refinement" value={model} onChange={setModel} />
          )}

          <Button onClick={start} loading={runner.isActive} disabled={!assetId || runner.isActive}>
            <Play size={16} />
            شروع تبدیل به متن
          </Button>
        </CardBody>
      </Card>

      {(runner.isActive || runner.job) && (
        <Card>
          <CardHeader
            title="وضعیت پردازش"
            action={
              runner.job && (
                <Badge tone={runner.status === "completed" ? "success" : runner.status === "failed" ? "danger" : "info"}>
                  {runner.status === "completed" ? "تکمیل شد" : runner.status === "failed" ? "ناموفق" : "در حال اجرا"}
                </Badge>
              )
            }
          />
          <CardBody className="space-y-4">
            <div>
              <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>{runner.stage || "در حال آماده‌سازی"}</span>
                {runner.progress != null && <span className="num">{Math.round(runner.progress * 100)}٪</span>}
              </div>
              <ProgressBar value={runner.progress} indeterminate={runner.progress == null} />
            </div>

            {runner.error && (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
                {runner.error}
              </div>
            )}

            {output?.refine_error && (
              <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                بازبینی با هوش مصنوعی ناموفق بود، اما متن خام ذخیره شد: {output.refine_error}
              </div>
            )}

            {output?.text && runner.status === "completed" && (
              <div className="rounded-xl border border-slate-200 dark:border-slate-800">
                <div className="flex items-center justify-between border-b border-slate-100 px-3.5 py-2 dark:border-slate-800">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 size={14} />
                    {output.refined ? "متن بازبینی‌شده" : "متن خام"} · {output.segment_count} قطعه زمان‌بندی‌شده
                  </span>
                </div>
                <p className="max-h-64 overflow-y-auto whitespace-pre-wrap p-3.5 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                  {output.text}
                </p>
              </div>
            )}

            <CliConsole lines={runner.logs} />
          </CardBody>
        </Card>
      )}
    </div>
  );
}
