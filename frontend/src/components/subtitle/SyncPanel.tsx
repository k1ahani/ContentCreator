/**
 * Subtitle synchronisation - the two ways to fix a track whose text is right
 * but whose timing is wrong.
 *
 * They are presented as two tabs rather than one clever button because they
 * genuinely answer different questions, and the user knows which one they are
 * in before we do:
 *
 * - **Automatic** ("با صدای ویدیو"): re-process the video's audio, measure
 *   where the words really are, and move the cues onto those measurements.
 *   Slow (it runs speech recognition), needs no input beyond picking the
 *   video, and is the right answer when the subtitles are a transcript of
 *   this audio - the raw-subtitle case.
 * - **Manual** ("دستی و گروهی"): arithmetic over every cue at once. Instant,
 *   no media read, and the right answer when the user can see the problem
 *   themselves ("everything is two seconds late", "the subtitles run at the
 *   wrong speed") or when the track is a translation whose words will never
 *   match the audio.
 *
 * Neither path edits cue *text*, and both funnel through the backend's
 * hygiene pass, so no synchronisation can leave the track in a state that
 * renders badly. The report shown after a manual retime is the backend's own
 * count of what it changed, not a guess made here.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AudioLines, Wand2, Timer, ArrowLeftRight } from "lucide-react";
import { useJobRunner } from "@/hooks/useJobRunner";
import { jobsApi, subtitlesApi } from "@/lib/api/resources";
import { CliConsole } from "@/components/console/CliConsole";
import { ApiError } from "@/lib/api/client";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  ProgressBar,
  Select,
  Tabs,
  toast,
} from "@/components/ui";
import type {
  MediaAsset,
  RetimeReport,
  SubtitleCue,
  SubtitleRetimeMode,
  SubtitleSyncStrategy,
} from "@/lib/api/types";

/** How the automatic pass should place cues it cannot match to the audio. */
const STRATEGIES: { value: SubtitleSyncStrategy; label: string; hint: string }[] = [
  {
    value: "auto",
    label: "خودکار (پیشنهادی)",
    hint: "ابتدا متن زیرنویس با کلمات شنیده‌شده تطبیق داده می‌شود؛ اگر مطابقت نداشت، قطعه‌ها روی بازه‌های گفتار توزیع می‌شوند.",
  },
  {
    value: "align",
    label: "فقط تطبیق متن با گفتار",
    hint: "اگر متن زیرنویس با گفتار ویدیو مطابقت نداشته باشد، عملیات با خطا متوقف می‌شود.",
  },
  {
    value: "distribute",
    label: "توزیع روی بازه‌های گفتار",
    hint: "بدون تطبیق متن؛ مناسب زیرنویس ترجمه‌شده که کلماتش با صدای ویدیو یکی نیست.",
  },
];

const MODES: { value: SubtitleRetimeMode; label: string; hint: string }[] = [
  {
    value: "shift",
    label: "جابه‌جایی زمانی",
    hint: "همه قطعه‌ها را با هم جلو یا عقب می‌برد. برای وقتی که کل زیرنویس با تأخیر یا زودتر از گفتار نمایش داده می‌شود.",
  },
  {
    value: "reading_speed",
    label: "سرعت نمایش زیرنویس",
    hint: "مدت هر قطعه از روی طول متن خودش و سرعت خواندن دلخواه محاسبه و قطعه‌ها پشت‌سرهم چیده می‌شوند.",
  },
  {
    value: "scale",
    label: "تغییر مقیاس زمان",
    hint: "همه زمان‌ها در یک ضریب ضرب می‌شوند. برای اختلافی که هرچه جلوتر می‌رویم بیشتر می‌شود (مثلاً اختلاف نرخ فریم).",
  },
  {
    value: "stretch",
    label: "کشیدن تا زمان مشخص",
    hint: "کل زیرنویس طوری کشیده یا فشرده می‌شود که آخرین قطعه در زمان دلخواه تمام شود.",
  },
];

export function SyncPanel({
  projectId,
  trackId,
  cues,
  mediaAssets,
  mediaDuration,
  onCuesChanged,
}: {
  projectId: string;
  trackId: string;
  cues: SubtitleCue[];
  /** Video and audio assets the automatic pass can listen to. */
  mediaAssets: MediaAsset[];
  /** The preview video's duration, used to keep cues inside the media. */
  mediaDuration: number;
  onCuesChanged: (cues: SubtitleCue[]) => void;
}) {
  const [tab, setTab] = useState<"auto" | "manual">("auto");
  const [assetId, setAssetId] = useState("");
  const [strategy, setStrategy] = useState<SubtitleSyncStrategy>("auto");

  const [mode, setMode] = useState<SubtitleRetimeMode>("shift");
  const [offset, setOffset] = useState(0);
  const [charsPerSecond, setCharsPerSecond] = useState(15);
  const [startSeconds, setStartSeconds] = useState(0);
  const [factor, setFactor] = useState(1);
  const [targetEnd, setTargetEnd] = useState(0);
  const [report, setReport] = useState<RetimeReport | null>(null);

  const effectiveAssetId = assetId || mediaAssets[0]?.id || "";
  const lastCueEnd = cues.length ? Math.max(...cues.map((c) => c.end)) : 0;

  const syncRunner = useJobRunner(
    (job) => {
      const output = job.output as { changed_count?: number; timing_source?: string };
      toast.success(
        output.timing_source === "audio_aligned"
          ? `زمان‌بندی ${output.changed_count ?? 0} قطعه با صدای ویدیو تنظیم شد`
          : `زمان‌بندی روی بازه‌های گفتار توزیع شد (${output.changed_count ?? 0} قطعه)`,
      );
      // The job wrote directly to the database, so the page's optimistic copy
      // of the cues is now stale - pull the authoritative list back.
      subtitlesApi.listCues(projectId, trackId).then((result) => onCuesChanged(result.items));
    },
    `cca:job:${projectId}:subtitle_sync:${trackId}`,
  );

  const retimeMutation = useMutation({
    mutationFn: () =>
      subtitlesApi.retime(projectId, trackId, {
        mode,
        offset_seconds: offset,
        factor,
        // Anchoring on the first cue is what makes "scale" fix drift alone:
        // anchoring at zero would move a track that already starts correctly.
        anchor_seconds: cues.length ? Math.min(...cues.map((c) => c.start)) : 0,
        chars_per_second: charsPerSecond,
        start_seconds: mode === "reading_speed" ? startSeconds : undefined,
        target_end_seconds: mode === "stretch" ? targetEnd : undefined,
        media_duration_seconds: mediaDuration || undefined,
      }),
    onSuccess: (result) => {
      onCuesChanged(result.items);
      setReport(result.report);
      toast.success(`زمان‌بندی ${result.report.changed_count} قطعه تغییر کرد`);
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "تغییر زمان‌بندی ناموفق بود"),
  });

  const startSync = () => {
    if (!effectiveAssetId) {
      toast.error("ابتدا یک فایل ویدئویی یا صوتی انتخاب کنید");
      return;
    }
    syncRunner.run(() =>
      jobsApi.syncSubtitles(projectId, {
        track_id: trackId,
        asset_id: effectiveAssetId,
        strategy,
      }),
    );
  };

  const syncOutput = syncRunner.job?.output as
    | { timing_source?: string; coverage?: number; changed_count?: number; max_shift_seconds?: number }
    | undefined;

  return (
    <Card>
      <CardHeader
        title="همگام‌سازی با ویدیو"
        description="زمان‌بندی قطعه‌ها را اصلاح می‌کند؛ متن زیرنویس دست‌نخورده می‌ماند"
      />
      <CardBody className="!p-0">
        <Tabs
          tabs={[
            { id: "auto", label: "با صدای ویدیو", icon: <AudioLines size={13} /> },
            { id: "manual", label: "دستی و گروهی", icon: <Timer size={13} /> },
          ]}
          active={tab}
          onChange={setTab}
        />

        <div className="space-y-4 p-4 sm:p-5">
          {tab === "auto" ? (
            <>
              <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
                صدای ویدیو دوباره پردازش می‌شود و زمان دقیق کلمات از روی گفتار اندازه‌گیری
                می‌شود؛ سپس قطعه‌های موجود روی همان زمان‌ها منتقل می‌شوند. این کار بسته به
                طول ویدیو ممکن است چند دقیقه طول بکشد.
              </p>

              <Field label="فایل ویدئویی یا صوتی">
                <Select value={effectiveAssetId} onChange={(e) => setAssetId(e.target.value)}>
                  {mediaAssets.length === 0 && <option value="">فایلی در پروژه نیست</option>}
                  {mediaAssets.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.original_filename}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field
                label="روش تطبیق"
                hint={STRATEGIES.find((s) => s.value === strategy)?.hint}
              >
                <Select
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value as SubtitleSyncStrategy)}
                >
                  {STRATEGIES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </Select>
              </Field>

              <Button
                onClick={startSync}
                loading={syncRunner.isActive}
                disabled={syncRunner.isActive || cues.length === 0}
              >
                <Wand2 size={15} />
                همگام‌سازی خودکار
              </Button>

              {(syncRunner.isActive || syncRunner.job) && (
                <div className="space-y-3">
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>{syncRunner.stage || "در حال آماده‌سازی"}</span>
                      {syncRunner.progress != null && (
                        <span className="num">{Math.round(syncRunner.progress * 100)}٪</span>
                      )}
                    </div>
                    <ProgressBar
                      value={syncRunner.progress}
                      indeterminate={syncRunner.progress == null}
                    />
                  </div>

                  {syncRunner.status === "completed" && syncOutput && (
                    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-emerald-50 p-3 text-xs text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                      <Badge tone={syncOutput.timing_source === "audio_aligned" ? "success" : "warning"}>
                        {syncOutput.timing_source === "audio_aligned"
                          ? "منطبق با صدا"
                          : "توزیع‌شده روی گفتار"}
                      </Badge>
                      <span>
                        {syncOutput.changed_count ?? 0} قطعه جابه‌جا شد
                      </span>
                      {syncOutput.timing_source === "audio_aligned" && (
                        <span>
                          · تطابق متن: <span className="num">{Math.round((syncOutput.coverage ?? 0) * 100)}٪</span>
                        </span>
                      )}
                    </div>
                  )}

                  {syncRunner.error && (
                    <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
                      {syncRunner.error}
                      {syncRunner.errorHint && (
                        <p className="mt-1 text-xs opacity-80">{syncRunner.errorHint}</p>
                      )}
                    </div>
                  )}

                  <CliConsole lines={syncRunner.logs} height="9rem" title="کنسول همگام‌سازی" />
                </div>
              )}
            </>
          ) : (
            <>
              <Field label="نوع تنظیم" hint={MODES.find((m) => m.value === mode)?.hint}>
                <Select
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as SubtitleRetimeMode);
                    setReport(null);
                  }}
                >
                  {MODES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </Select>
              </Field>

              {mode === "shift" && (
                <Field
                  label={`جابه‌جایی (${offset > 0 ? "+" : ""}${offset.toFixed(2)} ثانیه)`}
                  hint="عدد منفی زیرنویس را زودتر و عدد مثبت آن را دیرتر نمایش می‌دهد."
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={-30}
                      max={30}
                      step={0.05}
                      value={offset}
                      onChange={(e) => setOffset(Number(e.target.value))}
                      className="w-full accent-brand-600"
                      dir="ltr"
                    />
                    <Input
                      type="number"
                      ltr
                      step={0.05}
                      value={offset}
                      onChange={(e) => setOffset(Number(e.target.value) || 0)}
                      className="w-28"
                    />
                  </div>
                </Field>
              )}

              {mode === "reading_speed" && (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field
                    label={`سرعت خواندن (${charsPerSecond} نویسه در ثانیه)`}
                    hint="عدد کمتر یعنی هر قطعه بیشتر روی صفحه می‌ماند."
                  >
                    <input
                      type="range"
                      min={5}
                      max={30}
                      step={1}
                      value={charsPerSecond}
                      onChange={(e) => setCharsPerSecond(Number(e.target.value))}
                      className="w-full accent-brand-600"
                      dir="ltr"
                    />
                  </Field>
                  <Field label="شروع از ثانیه" hint="اولین قطعه از این زمان آغاز می‌شود.">
                    <Input
                      type="number"
                      ltr
                      min={0}
                      step={0.1}
                      value={startSeconds}
                      onChange={(e) => setStartSeconds(Math.max(0, Number(e.target.value) || 0))}
                    />
                  </Field>
                </div>
              )}

              {mode === "scale" && (
                <Field
                  label={`ضریب زمان (${factor.toFixed(3)}×)`}
                  hint="برای اختلاف نرخ فریم ۲۵ به ۲۳٫۹۷۶ عدد ۱٫۰۴۲۷ و برای حالت معکوس ۰٫۹۵۹ را وارد کنید."
                >
                  <Input
                    type="number"
                    ltr
                    min={0.1}
                    max={10}
                    step={0.001}
                    value={factor}
                    onChange={(e) => setFactor(Number(e.target.value) || 1)}
                  />
                </Field>
              )}

              {mode === "stretch" && (
                <Field
                  label="پایان آخرین قطعه در ثانیه"
                  hint={
                    mediaDuration
                      ? `مدت ویدیو ${mediaDuration.toFixed(1)} ثانیه و پایان فعلی زیرنویس ${lastCueEnd.toFixed(1)} ثانیه است.`
                      : `پایان فعلی زیرنویس ${lastCueEnd.toFixed(1)} ثانیه است.`
                  }
                >
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      ltr
                      min={0.1}
                      step={0.1}
                      value={targetEnd}
                      onChange={(e) => setTargetEnd(Number(e.target.value) || 0)}
                    />
                    {mediaDuration > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setTargetEnd(Number(mediaDuration.toFixed(2)))}
                      >
                        <ArrowLeftRight size={13} />
                        تا پایان ویدیو
                      </Button>
                    )}
                  </div>
                </Field>
              )}

              <Button
                onClick={() => retimeMutation.mutate()}
                loading={retimeMutation.isPending}
                disabled={
                  retimeMutation.isPending ||
                  cues.length === 0 ||
                  (mode === "stretch" && targetEnd <= 0)
                }
              >
                <Timer size={15} />
                اعمال روی همه قطعه‌ها
              </Button>

              {report && (
                <div className="space-y-1 rounded-xl bg-slate-50 p-3.5 text-xs text-slate-600 dark:bg-slate-800/40 dark:text-slate-300">
                  <p>
                    <span className="num">{report.changed_count}</span> از{" "}
                    <span className="num">{report.cue_count}</span> قطعه تغییر کرد؛ بیشترین
                    جابه‌جایی <span className="num">{report.max_shift_seconds.toFixed(2)}</span> ثانیه.
                  </p>
                  <p>
                    بازه جدید: <span className="num">{report.first_start.toFixed(2)}</span> تا{" "}
                    <span className="num">{report.last_end.toFixed(2)}</span> ثانیه.
                  </p>
                  {/*
                    These two are the render-safety guarantees, surfaced rather
                    than done silently: an overlap would have shown two
                    subtitle boxes at once in the burned-in video, and a
                    clamped cue would have run past the end of the picture.
                  */}
                  {report.overlaps_fixed > 0 && (
                    <p className="text-amber-600 dark:text-amber-400">
                      <span className="num">{report.overlaps_fixed}</span> هم‌پوشانی اصلاح شد تا
                      دو زیرنویس هم‌زمان روی تصویر نیفتد.
                    </p>
                  )}
                  {report.clamped_count > 0 && (
                    <p className="text-amber-600 dark:text-amber-400">
                      <span className="num">{report.clamped_count}</span> قطعه به داخل مدت ویدیو
                      برگردانده شد.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
