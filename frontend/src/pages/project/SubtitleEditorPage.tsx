/**
 * Feature 5, the main event: the subtitle timeline editor.
 *
 * Edits are optimistic - the local `cues` array updates immediately so
 * dragging feels instant - and persisted to the backend with a short debounce
 * per cue, so a fast drag or a burst of keystrokes does not fire one request
 * each. Split/merge go straight to the server because they change the cue
 * *count*, which optimistic local math would get wrong.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Download, Film, Settings2 } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { assetsApi, jobsApi, subtitlesApi } from "@/lib/api/resources";
import { assetDownloadUrl } from "@/lib/api/client";
import { VideoPreview } from "@/components/subtitle/VideoPreview";
import { SubtitleTimeline } from "@/components/subtitle/SubtitleTimeline";
import { CueDetailPanel } from "@/components/subtitle/CueDetailPanel";
import { StylePanel } from "@/components/subtitle/StylePanel";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, Select, ProgressBar, Badge, Tabs, toast } from "@/components/ui";
import { formatBytes } from "@/lib/format";
import type { SubtitleCue, SubtitleFormat } from "@/lib/api/types";

export function SubtitleEditorPage() {
  const { projectId } = useProject();
  const { trackId } = useParams<{ trackId: string }>();
  const queryClient = useQueryClient();

  const { data: track, isLoading } = useQuery({
    queryKey: ["subtitleTrack", projectId, trackId],
    queryFn: () => subtitlesApi.getTrack(projectId, trackId!),
    enabled: Boolean(trackId),
  });
  const { data: videos } = useQuery({
    queryKey: ["assets", projectId, "video"],
    queryFn: () => assetsApi.list(projectId, "video"),
  });

  const [cues, setCues] = useState<SubtitleCue[]>([]);
  const [selectedCueId, setSelectedCueId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [assetId, setAssetId] = useState("");
  const [rightTab, setRightTab] = useState<"cue" | "style">("cue");
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingWrites = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    if (track) setCues(track.cues);
  }, [track]);

  useEffect(() => {
    if (!assetId && videos?.items.length) setAssetId(videos.items[0].id);
  }, [videos, assetId]);

  const style = track?.style;

  const styleMutation = useMutation({
    mutationFn: (patch: Partial<NonNullable<typeof style>>) =>
      subtitlesApi.updateTrack(projectId, trackId!, { style: { ...style!, ...patch } }),
    onSuccess: (updated) => queryClient.setQueryData(["subtitleTrack", projectId, trackId], updated),
  });

  const addCueMutation = useMutation({
    mutationFn: () => {
      const start = currentTime;
      return subtitlesApi.addCue(projectId, trackId!, { start, end: start + 2, text: "" });
    },
    onSuccess: (cue) => {
      setCues((prev) => [...prev, cue].sort((a, b) => a.start - b.start));
      setSelectedCueId(cue.id);
    },
  });

  const deleteCueMutation = useMutation({
    mutationFn: (cueId: string) => subtitlesApi.deleteCue(projectId, trackId!, cueId),
    onSuccess: (_r, cueId) => {
      setCues((prev) => prev.filter((c) => c.id !== cueId));
      if (selectedCueId === cueId) setSelectedCueId(null);
    },
  });

  const splitCueMutation = useMutation({
    mutationFn: ({ cueId, at }: { cueId: string; at: number }) =>
      subtitlesApi.splitCue(projectId, trackId!, cueId, at),
    onSuccess: (result) => setCues(result.items),
  });

  const mergeCueMutation = useMutation({
    mutationFn: (cueId: string) => subtitlesApi.mergeCue(projectId, trackId!, cueId),
    onSuccess: (result) => setCues(result.items),
  });

  const exportMutation = useMutation({
    mutationFn: (format: SubtitleFormat) => subtitlesApi.export(projectId, trackId!, format),
    onSuccess: () => {
      toast.success("فایل زیرنویس ذخیره شد");
      queryClient.invalidateQueries({ queryKey: ["assets", projectId] });
    },
  });

  const renderRunner = useJobRunner(() => toast.success("رندر ویدیو با زیرنویس تکمیل شد"));

  function commitCue(cueId: string, patch: Partial<Pick<SubtitleCue, "text" | "start" | "end">>) {
    setCues((prev) => prev.map((c) => (c.id === cueId ? { ...c, ...patch } : c)));

    const existing = pendingWrites.current.get(cueId);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      subtitlesApi.updateCue(projectId, trackId!, cueId, patch).catch(() => {
        toast.error("ذخیره تغییرات ناموفق بود");
      });
      pendingWrites.current.delete(cueId);
    }, 400);
    pendingWrites.current.set(cueId, timer);
  }

  const sortedCues = useMemo(() => [...cues].sort((a, b) => a.start - b.start), [cues]);
  const selectedCue = sortedCues.find((c) => c.id === selectedCueId) ?? null;
  const activeCue = sortedCues.find((c) => currentTime >= c.start && currentTime < c.end) ?? null;
  const selectedIndex = selectedCue ? sortedCues.findIndex((c) => c.id === selectedCue.id) : -1;

  const startRender = () => {
    if (!assetId) {
      toast.error("ابتدا یک فایل ویدئویی انتخاب کنید");
      return;
    }
    renderRunner.run(() => jobsApi.renderSubtitles(projectId, { track_id: trackId!, asset_id: assetId }));
  };

  const renderOutput = renderRunner.job?.output as { asset_id?: string; output_size_bytes?: number } | undefined;

  if (isLoading || !track) {
    return <p className="text-sm text-slate-400">در حال بارگذاری...</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">{track.name}</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">ویرایش تایم‌لاین زیرنویس</p>
        </div>
        <div className="flex gap-2">
          {(["srt", "vtt", "ass"] as const).map((fmt) => (
            <Button key={fmt} size="sm" variant="outline" onClick={() => exportMutation.mutate(fmt)}>
              <Download size={13} />
              <span className="ltr">.{fmt}</span>
            </Button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Card>
            <CardBody className="space-y-3">
              <Select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
                <option value="">انتخاب فایل ویدئویی برای پیش‌نمایش...</option>
                {videos?.items.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.original_filename}
                  </option>
                ))}
              </Select>
              {assetId && style && (
                <VideoPreview
                  ref={videoRef}
                  assetId={assetId}
                  currentTime={currentTime}
                  activeCue={activeCue}
                  style={style}
                  onTimeUpdate={setCurrentTime}
                  onLoadedMetadata={setDuration}
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="تایم‌لاین"
              action={
                <Button size="sm" onClick={() => addCueMutation.mutate()}>
                  <Plus size={14} />
                  زیرنویس جدید
                </Button>
              }
            />
            <CardBody>
              <SubtitleTimeline
                cues={sortedCues}
                duration={duration || sortedCues.at(-1)?.end || 60}
                currentTime={currentTime}
                selectedCueId={selectedCueId}
                onSeek={(t) => {
                  if (videoRef.current) videoRef.current.currentTime = t;
                  setCurrentTime(t);
                }}
                onSelect={(id) => {
                  setSelectedCueId(id);
                  if (id) setRightTab("cue");
                }}
                onCueChange={(cueId, start, end) => commitCue(cueId, { start, end })}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="رندر روی ویدیو"
              description="ساخت یک فایل MP4 جدید با زیرنویس ثابت؛ فایل اصلی تغییر نمی‌کند"
              action={
                <Button onClick={startRender} loading={renderRunner.isActive} disabled={renderRunner.isActive}>
                  <Film size={15} />
                  رندر ویدیو
                </Button>
              }
            />
            {(renderRunner.isActive || renderRunner.job) && (
              <CardBody className="space-y-3">
                <div>
                  <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>{renderRunner.stage || "در حال آماده‌سازی"}</span>
                    {renderRunner.progress != null && (
                      <span className="num">{Math.round(renderRunner.progress * 100)}٪</span>
                    )}
                  </div>
                  <ProgressBar value={renderRunner.progress} indeterminate={renderRunner.progress == null} />
                </div>
                {renderRunner.status === "completed" && renderOutput?.asset_id && (
                  <div className="flex items-center justify-between rounded-lg bg-emerald-50 p-3 text-xs dark:bg-emerald-950/30">
                    <span className="text-emerald-700 dark:text-emerald-300">
                      رندر کامل شد ({formatBytes(renderOutput.output_size_bytes ?? 0)})
                    </span>
                    <a
                      href={assetDownloadUrl(renderOutput.asset_id)}
                      className="font-medium text-emerald-700 underline dark:text-emerald-300"
                    >
                      دانلود
                    </a>
                  </div>
                )}
                {renderRunner.error && (
                  <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
                    {renderRunner.error}
                  </div>
                )}
                <CliConsole lines={renderRunner.logs} title="کنسول FFmpeg" />
              </CardBody>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardBody className="!p-0">
              <Tabs
                tabs={[
                  { id: "cue", label: "قطعه انتخابی" },
                  { id: "style", label: "ظاهر", icon: <Settings2 size={13} /> },
                ]}
                active={rightTab}
                onChange={setRightTab}
              />
              <div className="p-4">
                {rightTab === "cue" ? (
                  selectedCue ? (
                    <CueDetailPanel
                      cue={selectedCue}
                      hasNext={selectedIndex >= 0 && selectedIndex < sortedCues.length - 1}
                      onTextChange={(text) => commitCue(selectedCue.id, { text })}
                      onTimeChange={(start, end) => commitCue(selectedCue.id, { start, end })}
                      onDelete={() => deleteCueMutation.mutate(selectedCue.id)}
                      onSplit={(at) => splitCueMutation.mutate({ cueId: selectedCue.id, at })}
                      onMerge={() => mergeCueMutation.mutate(selectedCue.id)}
                      onSeekToStart={() => {
                        if (videoRef.current) videoRef.current.currentTime = selectedCue.start;
                        setCurrentTime(selectedCue.start);
                      }}
                    />
                  ) : (
                    <p className="py-8 text-center text-sm text-slate-400">
                      روی یکی از قطعه‌های تایم‌لاین کلیک کنید
                    </p>
                  )
                ) : (
                  style && <StylePanel style={style} onChange={(patch) => styleMutation.mutate(patch)} />
                )}
              </div>
            </CardBody>
          </Card>

          {selectedCue && <Badge tone="info">قطعه {selectedIndex + 1} از {sortedCues.length}</Badge>}
        </div>
      </div>
    </div>
  );
}
