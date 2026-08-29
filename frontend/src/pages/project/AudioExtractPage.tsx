/**
 * Feature 1: Video -> Audio.
 *
 * Select an MP4 from the local filesystem, extract speech-optimised audio
 * with FFmpeg (see backend/app/media/audio.py), and register the result as a
 * project asset. This talks to real endpoints end to end - nothing here is a
 * placeholder (per requirement 40).
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileVideo, FolderOpen, Play, X, CheckCircle2 } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { assetsApi, jobsApi, systemApi } from "@/lib/api/resources";
import { FilePickerDialog } from "@/components/media/FilePickerDialog";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, ProgressBar, Badge, toast } from "@/components/ui";
import { formatBytes, formatDuration } from "@/lib/format";
import { ApiError } from "@/lib/api/client";
import type { ImportedAssetResponse } from "@/lib/api/types";

export function AudioExtractPage() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selected, setSelected] = useState<ImportedAssetResponse | null>(null);
  const [preset, setPreset] = useState<string>("opus");

  const { data: capabilities } = useQuery({
    queryKey: ["mediaCapabilities"],
    queryFn: systemApi.media,
  });

  const importMutation = useMutation({
    mutationFn: (path: string) => assetsApi.import(projectId, path, "video", false),
    onSuccess: (result) => {
      setSelected(result);
      queryClient.invalidateQueries({ queryKey: ["assets", projectId] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "خطا در بارگذاری فایل"),
  });

  const runner = useJobRunner((job) => {
    toast.success("استخراج صدا با موفقیت انجام شد");
    void job;
  }, `cca:job:${projectId}:audio_extract`);

  const extract = () => {
    if (!selected) return;
    runner.run(() => jobsApi.extractAudio(projectId, selected.asset.id, preset));
  };

  const output = runner.job?.output as
    | { filename?: string; output_size_bytes?: number; input_size_bytes?: number; compression_ratio?: number; processing_seconds?: number; duration_display?: string; asset_id?: string }
    | undefined;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">استخراج صدا از ویدیو</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          فایل ویدئویی را انتخاب کنید تا صدای بهینه‌شده برای تبدیل به متن استخراج شود
        </p>
      </div>

      <Card>
        <CardHeader title="۱. انتخاب فایل ویدئویی" />
        <CardBody>
          {!selected ? (
            <button
              onClick={() => setPickerOpen(true)}
              className="flex w-full flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-slate-300 py-10 text-center transition-colors hover:border-brand-400 hover:bg-brand-50/30 dark:border-slate-700 dark:hover:border-brand-700 dark:hover:bg-brand-950/10"
            >
              <FolderOpen size={32} className="text-slate-400" />
              <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                انتخاب فایل ویدئویی
              </span>
              <span className="text-xs text-slate-400">MP4، MKV، MOV و سایر فرمت‌های رایج</span>
            </button>
          ) : (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-400">
                  <FileVideo size={20} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                    {selected.asset.original_filename}
                  </p>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                    <span className="num">{formatBytes(selected.asset.size_bytes)}</span>
                    {selected.probe?.duration_seconds != null && (
                      <span className="num">{formatDuration(selected.probe.duration_seconds)}</span>
                    )}
                    {selected.probe?.width && (
                      <span className="num">
                        {selected.probe.width}×{selected.probe.height}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <button
                onClick={() => {
                  setSelected(null);
                  runner.reset();
                }}
                className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X size={16} />
              </button>
            </div>
          )}
          {importMutation.isPending && (
            <p className="mt-2 text-xs text-slate-400">در حال خواندن اطلاعات فایل...</p>
          )}
        </CardBody>
      </Card>

      {selected && (
        <Card>
          <CardHeader title="۲. تنظیمات استخراج" description="کیفیت صدا برای تبدیل به متن بهینه شده است" />
          <CardBody>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {(capabilities?.audio_presets ?? []).map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPreset(p.id)}
                  className={
                    "rounded-xl border p-3.5 text-start transition-colors " +
                    (preset === p.id
                      ? "border-brand-500 bg-brand-50 dark:border-brand-600 dark:bg-brand-950/30"
                      : "border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700")
                  }
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-200">{p.label_fa}</span>
                    {preset === p.id && <CheckCircle2 size={16} className="text-brand-600 dark:text-brand-400" />}
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{p.description_fa}</p>
                  <p className="num mt-1.5 text-xs text-slate-400">
                    تقریباً {p.approx_mb_per_hour} مگابایت به ازای هر ساعت
                  </p>
                </button>
              ))}
            </div>

            <div className="mt-5 flex items-center gap-3">
              <Button onClick={extract} loading={runner.isActive} disabled={runner.isActive}>
                <Play size={16} />
                استخراج فایل صوتی
              </Button>
              {runner.isActive && (
                <Button variant="outline" onClick={() => runner.cancel()}>
                  لغو
                </Button>
              )}
            </div>
          </CardBody>
        </Card>
      )}

      {(runner.isActive || runner.job) && (
        <Card>
          <CardHeader
            title="وضعیت استخراج"
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
                {runner.errorHint && <p className="mt-1 text-xs opacity-80">{runner.errorHint}</p>}
              </div>
            )}

            {output && runner.status === "completed" && (
              <div className="grid grid-cols-2 gap-3 rounded-xl bg-emerald-50 p-4 text-xs dark:bg-emerald-950/30 sm:grid-cols-4">
                <Stat label="حجم ورودی" value={formatBytes(output.input_size_bytes ?? 0)} />
                <Stat label="حجم خروجی" value={formatBytes(output.output_size_bytes ?? 0)} />
                <Stat label="نسبت فشرده‌سازی" value={`${output.compression_ratio?.toFixed(1)}×`} />
                <Stat label="زمان پردازش" value={`${output.processing_seconds?.toFixed(1)} ثانیه`} />
              </div>
            )}

            <CliConsole lines={runner.logs} title="کنسول FFmpeg" />
          </CardBody>
        </Card>
      )}

      <FilePickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => importMutation.mutate(path)}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-emerald-600 dark:text-emerald-400">{label}</p>
      <p className="num mt-0.5 font-semibold text-emerald-800 dark:text-emerald-200">{value}</p>
    </div>
  );
}
