/**
 * Requirement 25: a real-time CLI console for AI/media job activity, with
 * history of everything the platform has run.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Terminal, X } from "lucide-react";
import { jobsApi } from "@/lib/api/resources";
import { useJobWatcher } from "@/hooks/useJobWatcher";
import { JobStatusBadge } from "@/components/JobStatusBadge";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardBody, EmptyState, ProgressBar, Badge } from "@/components/ui";
import { formatRelativeTime } from "@/lib/format";
import type { JobStatus } from "@/lib/api/types";

const JOB_LABELS: Record<string, string> = {
  audio_extract: "استخراج صدا",
  transcribe: "تبدیل گفتار به متن",
  text_task: "پردازش متن هوش مصنوعی",
  subtitle_generate: "ساخت زیرنویس",
  subtitle_render: "رندر زیرنویس",
  tts_synthesize: "تولید گفتار",
};

export function ConsolePage() {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");

  const { data: jobs, isLoading } = useQuery({
    queryKey: ["jobs", "console", statusFilter],
    queryFn: () => jobsApi.list({ status: statusFilter || undefined }),
    refetchInterval: 4000,
  });

  const watcher = useJobWatcher(selectedJobId ?? undefined);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100 sm:text-2xl">کنسول هوش مصنوعی</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          فعالیت زنده و تاریخچه تمام وظایف پردازشی پلتفرم
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["", "running", "completed", "failed", "cancelled"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors " +
              (statusFilter === s
                ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                : "border-slate-200 text-slate-500 dark:border-slate-800 dark:text-slate-400")
            }
          >
            {s === "" ? "همه" : { running: "در حال اجرا", completed: "تکمیل‌شده", failed: "ناموفق", cancelled: "لغوشده" }[s]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="max-h-[36rem] overflow-hidden lg:max-h-[42rem]">
          <div className="max-h-full overflow-y-auto">
            {isLoading ? (
              <p className="p-4 text-sm text-slate-400">در حال بارگذاری...</p>
            ) : !jobs || jobs.items.length === 0 ? (
              <EmptyState icon={<Terminal size={32} />} title="وظیفه‌ای ثبت نشده است" />
            ) : (
              jobs.items.map((job) => (
                <button
                  key={job.id}
                  onClick={() => setSelectedJobId(job.id)}
                  className={
                    "flex w-full flex-col gap-1 border-b border-slate-100 px-4 py-3 text-start last:border-0 dark:border-slate-800 " +
                    (selectedJobId === job.id ? "bg-brand-50 dark:bg-brand-950/30" : "hover:bg-slate-50 dark:hover:bg-slate-800/50")
                  }
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                      {JOB_LABELS[job.type] ?? job.type}
                    </span>
                    <JobStatusBadge status={job.status} />
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    {job.model && <span className="ltr">{job.model}</span>}
                    <span>{formatRelativeTime(job.created_at)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardBody className="space-y-4">
            {!selectedJobId ? (
              <EmptyState icon={<Terminal size={32} />} title="یک وظیفه را از فهرست انتخاب کنید" />
            ) : watcher.isLoading || !watcher.job ? (
              <p className="text-sm text-slate-400">در حال بارگذاری...</p>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                      {JOB_LABELS[watcher.job.type] ?? watcher.job.type}
                    </h3>
                    <JobStatusBadge status={watcher.job.status} />
                  </div>
                  <button onClick={() => setSelectedJobId(null)} className="text-slate-400 hover:text-slate-600">
                    <X size={16} />
                  </button>
                </div>

                {watcher.job.provider && (
                  <div className="flex gap-2 text-xs text-slate-500 dark:text-slate-400">
                    <Badge tone="brand">{watcher.job.provider}</Badge>
                    {watcher.job.model && <span className="ltr">{watcher.job.model}</span>}
                  </div>
                )}

                {(watcher.job.status === "running" || watcher.job.status === "queued") && (
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>{watcher.job.stage || "در حال اجرا"}</span>
                      {watcher.job.progress != null && <span className="num">{Math.round(watcher.job.progress * 100)}٪</span>}
                    </div>
                    <ProgressBar value={watcher.job.progress} indeterminate={watcher.job.progress == null} />
                  </div>
                )}

                {watcher.job.error && (
                  <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
                    {watcher.job.error}
                  </div>
                )}

                <CliConsole lines={watcher.logs} height="24rem" />
              </>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
