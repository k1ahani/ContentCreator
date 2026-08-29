import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CheckCircle2, XCircle, FolderPlus, ArrowLeft, Loader2 } from "lucide-react";
import { systemApi, projectsApi, jobsApi } from "@/lib/api/resources";
import { Card, CardHeader, CardBody, Badge, Button, EmptyState, Skeleton } from "@/components/ui";
import { formatRelativeTime, formatNumber } from "@/lib/format";
import { JobStatusBadge } from "@/components/JobStatusBadge";

export function DashboardPage() {
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: systemApi.status,
  });
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ["projects", { limit: 5 }],
    queryFn: () => projectsApi.list(),
  });
  const { data: activeJobs } = useQuery({
    queryKey: ["jobs", "active"],
    queryFn: jobsApi.listActive,
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100 sm:text-2xl">داشبورد</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          خلاصه‌ای از وضعیت پلتفرم و کارهای در حال انجام
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader
              title="وابستگی‌های سیستم"
              description="ابزارهایی که ویژگی‌های پلتفرم به آن‌ها نیاز دارند"
            />
            <CardBody>
              {statusLoading || !status ? (
                <div className="space-y-3">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : (
                <div className="space-y-2.5">
                  {status.dependencies.map((dep) => (
                    <div
                      key={dep.id}
                      className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800"
                    >
                      <div className="flex items-center gap-3">
                        {dep.available ? (
                          <CheckCircle2 size={20} className="shrink-0 text-emerald-500" />
                        ) : (
                          <XCircle size={20} className="shrink-0 text-red-400" />
                        )}
                        <div>
                          <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                            {dep.label_fa}
                          </p>
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {dep.detail_fa}
                            {dep.hint_fa && !dep.available && (
                              <span className="block text-amber-600 dark:text-amber-400">{dep.hint_fa}</span>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {dep.version && <span className="ltr text-xs text-slate-400">{dep.version}</span>}
                        <Badge tone={dep.available ? "success" : dep.required ? "danger" : "warning"}>
                          {dep.available ? "فعال" : dep.required ? "الزامی" : "اختیاری"}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader title="وظایف در حال اجرا" />
          <CardBody>
            {!activeJobs || activeJobs.items.length === 0 ? (
              <p className="py-4 text-center text-sm text-slate-400">در حال حاضر وظیفه فعالی وجود ندارد</p>
            ) : (
              <div className="space-y-2">
                {activeJobs.items.map((job) => (
                  <div key={job.id} className="rounded-lg border border-slate-100 p-2.5 text-xs dark:border-slate-800">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-300">
                        <Loader2 size={12} className="animate-spin" />
                        {jobTypeLabel(job.type)}
                      </span>
                      <JobStatusBadge status={job.status} />
                    </div>
                    {job.stage && <p className="mt-1 truncate text-slate-500 dark:text-slate-400">{job.stage}</p>}
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="پروژه‌های اخیر"
          action={
            <Link to="/projects">
              <Button variant="ghost" size="sm">
                مشاهده همه
                <ArrowLeft size={14} />
              </Button>
            </Link>
          }
        />
        <CardBody>
          {projectsLoading ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          ) : !projects || projects.items.length === 0 ? (
            <EmptyState
              icon={<FolderPlus size={32} />}
              title="هنوز پروژه‌ای نساخته‌اید"
              description="یک پروژه جدید بسازید تا کار تولید محتوا را شروع کنید."
              action={
                <Link to="/projects">
                  <Button size="sm">ساخت پروژه جدید</Button>
                </Link>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {projects.items.slice(0, 6).map((project) => (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className="rounded-xl border border-slate-100 p-3.5 transition-colors hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-800 dark:hover:border-brand-800 dark:hover:bg-brand-950/20"
                >
                  <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-200">{project.name}</p>
                  <div className="mt-1.5 flex items-center gap-3 text-xs text-slate-400">
                    <span>{formatNumber(project.asset_count)} فایل</span>
                    <span>{formatRelativeTime(project.updated_at)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function jobTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    audio_extract: "استخراج صدا",
    transcribe: "تبدیل گفتار به متن",
    text_task: "پردازش متن",
    subtitle_generate: "ساخت زیرنویس",
    subtitle_render: "رندر زیرنویس",
    tts_synthesize: "تولید گفتار",
  };
  return labels[type] ?? type;
}
