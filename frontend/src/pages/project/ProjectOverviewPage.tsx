import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AudioLines, Captions, FileText, Subtitles, Mic, ArrowLeft } from "lucide-react";
import { assetsApi, documentsApi } from "@/lib/api/resources";
import { useProject } from "@/hooks/useProject";
import { Card, CardHeader, CardBody, Skeleton, Badge } from "@/components/ui";
import { formatBytes, formatDuration, formatRelativeTime } from "@/lib/format";

const STEPS = [
  { label: "استخراج صدا", path: "audio", icon: AudioLines, assetType: "audio" },
  { label: "تبدیل به متن", path: "transcribe", icon: Captions, assetType: null },
  { label: "ویرایش و ترجمه", path: "text", icon: FileText, assetType: null },
  { label: "زیرنویس", path: "subtitles", icon: Subtitles, assetType: "subtitle" },
  { label: "تبدیل متن به صدا", path: "speech", icon: Mic, assetType: "voice" },
] as const;

export function ProjectOverviewPage() {
  const { projectId, data: project } = useProject();
  const { data: assets, isLoading: assetsLoading } = useQuery({
    queryKey: ["assets", projectId],
    queryFn: () => assetsApi.list(projectId),
  });
  const { data: documents, isLoading: docsLoading } = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => documentsApi.list(projectId),
  });

  return (
    <div className="space-y-6">
      {project?.description && (
        <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-400">{project.description}</p>
      )}

      <Card>
        <CardHeader title="جریان کار پروژه" description="مسیر پیشنهادی از ویدیو تا خروجی نهایی" />
        <CardBody>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((step) => (
              <Link
                key={step.path}
                to={step.path}
                className="group flex flex-col items-center gap-2 rounded-xl border border-slate-100 p-4 text-center transition-colors hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-800 dark:hover:border-brand-800 dark:hover:bg-brand-950/20"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-500 transition-colors group-hover:bg-brand-100 group-hover:text-brand-600 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-brand-950 dark:group-hover:text-brand-400">
                  <step.icon size={18} />
                </div>
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">{step.label}</span>
              </Link>
            ))}
          </div>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="فایل‌های رسانه‌ای"
            action={
              <Link to="audio" className="flex items-center gap-1 text-xs text-brand-600 hover:underline dark:text-brand-400">
                افزودن ویدیو <ArrowLeft size={12} />
              </Link>
            }
          />
          <CardBody>
            {assetsLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : !assets || assets.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-400">هنوز فایلی اضافه نشده است</p>
            ) : (
              <div className="space-y-2">
                {assets.items.slice(0, 6).map((asset) => (
                  <div
                    key={asset.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2 text-xs dark:border-slate-800"
                  >
                    <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                      {asset.original_filename}
                    </span>
                    <div className="flex shrink-0 items-center gap-2 text-slate-400">
                      <Badge tone="neutral">{assetTypeLabel(asset.type)}</Badge>
                      <span className="num">{formatBytes(asset.size_bytes)}</span>
                      {asset.duration_seconds != null && (
                        <span className="num">{formatDuration(asset.duration_seconds)}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="اسناد متنی" />
          <CardBody>
            {docsLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : !documents || documents.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-400">هنوز سندی ساخته نشده است</p>
            ) : (
              <div className="space-y-2">
                {documents.items.slice(0, 6).map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2 text-xs dark:border-slate-800"
                  >
                    <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                      {doc.title || documentTypeLabel(doc.type)}
                    </span>
                    <div className="flex shrink-0 items-center gap-2 text-slate-400">
                      <Badge tone="neutral">نسخه {doc.version}</Badge>
                      <span>{formatRelativeTime(doc.updated_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function assetTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    video: "ویدیو",
    audio: "صدا",
    transcript: "رونوشت",
    subtitle: "زیرنویس",
    voice: "گفتار",
    rendered_video: "ویدیوی رندرشده",
  };
  return labels[type] ?? type;
}

function documentTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    transcript_raw: "رونوشت خام",
    transcript_refined: "رونوشت بازبینی‌شده",
    edited: "متن ویرایش‌شده",
    translation: "ترجمه",
    speech_script: "متن گفتار",
    note: "یادداشت",
  };
  return labels[type] ?? type;
}
