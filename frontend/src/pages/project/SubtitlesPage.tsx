/**
 * Feature 5, entry point: list subtitle tracks, create one from a transcript,
 * or start a blank track to build by hand.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Subtitles as SubtitlesIcon, Clock, Trash2 } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { documentsApi, jobsApi, subtitlesApi } from "@/lib/api/resources";
import { useJobRunner } from "@/hooks/useJobRunner";
import { Card, CardBody, Button, Dialog, Field, Select, EmptyState, Badge, toast } from "@/components/ui";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import { ApiError } from "@/lib/api/client";
import type { Language } from "@/lib/api/types";

export function SubtitlesPage() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const [generateOpen, setGenerateOpen] = useState(false);
  const [docId, setDocId] = useState("");
  const [language, setLanguage] = useState<Language>("fa");

  const { data: tracks, isLoading } = useQuery({
    queryKey: ["subtitleTracks", projectId],
    queryFn: () => subtitlesApi.listTracks(projectId),
  });
  const { data: documents } = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => documentsApi.list(projectId),
  });

  const createBlankMutation = useMutation({
    mutationFn: () => subtitlesApi.createTrack(projectId, { name: "زیرنویس جدید", language: "fa" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["subtitleTracks", projectId] }),
  });

  const generateRunner = useJobRunner(() => {
    queryClient.invalidateQueries({ queryKey: ["subtitleTracks", projectId] });
    setGenerateOpen(false);
    toast.success("زیرنویس ساخته شد");
  }, `cca:job:${projectId}:subtitle_generate`);

  const deleteTrackMutation = useMutation({
    mutationFn: (trackId: string) => subtitlesApi.deleteTrack(projectId, trackId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["subtitleTracks", projectId] });
      toast.success("زیرنویس حذف شد");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "خطا در حذف زیرنویس"),
  });

  const generate = () => {
    if (!docId) return;
    generateRunner.run(() =>
      jobsApi.generateSubtitles(projectId, { document_id: docId, language }),
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">زیرنویس</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            ساخت، ویرایش و رندر زیرنویس روی ویدیو
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => createBlankMutation.mutate()} loading={createBlankMutation.isPending}>
            <Plus size={16} />
            زیرنویس خالی
          </Button>
          <Button onClick={() => setGenerateOpen(true)}>
            <SubtitlesIcon size={16} />
            ساخت از رونوشت
          </Button>
        </div>
      </div>

      {isLoading ? null : !tracks || tracks.items.length === 0 ? (
        <EmptyState
          icon={<SubtitlesIcon size={40} />}
          title="هنوز زیرنویسی ساخته نشده است"
          description="از یک رونوشت زیرنویس بسازید یا یک زیرنویس خالی شروع کنید."
          action={<Button onClick={() => setGenerateOpen(true)}>ساخت از رونوشت</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {tracks.items.map((track) => (
            <Card key={track.id} className="relative transition-colors hover:border-brand-300 dark:hover:border-brand-800">
              <Link to={track.id} className="block">
                <CardBody>
                  <div className="pe-8">
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {track.name || "بدون نام"}
                    </h3>
                    <Badge tone="neutral">{track.language === "fa" ? "فارسی" : "English"}</Badge>
                  </div>
                  <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <Clock size={12} />
                      {formatDuration(track.cues.at(-1)?.end ?? 0)}
                    </span>
                    <span>{track.cues.length} قطعه</span>
                    <span className="me-auto">{formatRelativeTime(track.updated_at)}</span>
                  </div>
                </CardBody>
              </Link>
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (confirm(`زیرنویس «${track.name || "بدون نام"}» حذف شود؟ این عملیات قابل بازگشت نیست.`)) {
                    deleteTrackMutation.mutate(track.id);
                  }
                }}
                title="حذف زیرنویس"
                className="absolute end-3 top-3 rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50 dark:hover:text-red-400"
              >
                <Trash2 size={15} />
              </button>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        title="ساخت زیرنویس از رونوشت"
        footer={
          <>
            <Button variant="ghost" onClick={() => setGenerateOpen(false)}>
              انصراف
            </Button>
            <Button onClick={generate} loading={generateRunner.isActive} disabled={!docId}>
              ساخت زیرنویس
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="سند متنی">
            <Select value={docId} onChange={(e) => setDocId(e.target.value)}>
              <option value="">انتخاب کنید...</option>
              {documents?.items.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.title || doc.type} (نسخه {doc.version})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="زبان">
            <Select value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
              <option value="fa">فارسی</option>
              <option value="en">English</option>
            </Select>
          </Field>
          {generateRunner.error && (
            <p className="text-sm text-red-600 dark:text-red-400">{generateRunner.error}</p>
          )}
        </div>
      </Dialog>
    </div>
  );
}
