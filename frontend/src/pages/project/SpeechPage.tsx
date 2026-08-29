/**
 * Feature 6: Text -> Speech.
 *
 * Every voice, language and provider comes from `/api/ai/tts/*` - nothing is
 * hardcoded (same principle as the model registry: see docs/AI_SYSTEM.md).
 * Two real providers are wired up on the backend (Edge neural, offline
 * SAPI5); this page just renders whichever the registry reports.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Play, Volume2 } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { aiApi, jobsApi } from "@/lib/api/resources";
import { assetUrl } from "@/lib/api/client";
import { SpeechSegmentEditor, type EditorSegment } from "@/components/tts/SpeechSegmentEditor";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, Select, Field, ProgressBar, Badge, toast } from "@/components/ui";
import type { Language, SpeakingStyle } from "@/lib/api/types";

const STYLE_LABELS: Record<SpeakingStyle, string> = {
  neutral: "خنثی",
  friendly: "دوستانه",
  casual: "غیررسمی",
  professional: "حرفه‌ای",
  formal: "رسمی",
  energetic: "پرانرژی",
  calm: "آرام",
};

export function SpeechPage() {
  const { projectId } = useProject();
  const [language, setLanguage] = useState<Language>("fa");
  const [voiceId, setVoiceId] = useState("");
  const [style, setStyle] = useState<SpeakingStyle>("neutral");
  const [rate, setRate] = useState(1.0);
  const [pitch, setPitch] = useState(0);
  const [segments, setSegments] = useState<EditorSegment[]>([
    { id: crypto.randomUUID(), kind: "text", text: "" },
  ]);

  const { data: voices } = useQuery({
    queryKey: ["voices", language],
    queryFn: () => aiApi.voices({ language }),
  });
  const { data: providers } = useQuery({
    queryKey: ["ttsProviders"],
    queryFn: () => aiApi.ttsProviders(true),
  });

  const selectedVoice = voices?.items.find((v) => v.id === voiceId) ?? voices?.items[0];
  const effectiveVoiceId = voiceId || selectedVoice?.id || "";

  const runner = useJobRunner(() => toast.success("تولید گفتار کامل شد"));

  const synthesize = () => {
    const hasText = segments.some((s) => s.kind === "text" && (s.text ?? "").trim());
    if (!hasText) {
      toast.error("متنی برای تبدیل به گفتار وجود ندارد");
      return;
    }
    if (!effectiveVoiceId) {
      toast.error("صدایی برای این زبان در دسترس نیست");
      return;
    }
    runner.run(() =>
      jobsApi.synthesizeSpeech(projectId, {
        segments: segments
          .filter((s) => s.kind === "pause" || (s.text ?? "").trim())
          .map((s) => (s.kind === "text" ? { kind: "text", id: s.id, text: s.text } : { kind: "pause", id: s.id, seconds: s.seconds })),
        voice_id: effectiveVoiceId,
        language,
        style,
        rate,
        pitch,
      }),
    );
  };

  const output = runner.job?.output as { asset_id?: string; duration_display?: string; pause_count?: number } | undefined;

  const unavailableProviders = providers?.items.filter((p) => !p.available) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">تبدیل متن به صدا</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          متن را به همراه مکث‌های دلخواه به گفتار طبیعی تبدیل کنید
        </p>
      </div>

      {unavailableProviders.length > 0 && (
        <div className="rounded-xl bg-amber-50 p-3.5 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
          {unavailableProviders.map((p) => (
            <p key={p.id}>
              {p.display_name}: {p.unavailable_reason} {p.hint}
            </p>
          ))}
        </div>
      )}

      <Card>
        <CardHeader title="متن گفتار" />
        <CardBody>
          <SpeechSegmentEditor segments={segments} onChange={setSegments} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="تنظیمات صدا" />
        <CardBody className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="زبان">
              <div className="flex gap-2">
                {(["fa", "en"] as const).map((lang) => (
                  <button
                    key={lang}
                    onClick={() => {
                      setLanguage(lang);
                      setVoiceId("");
                    }}
                    className={
                      "flex-1 rounded-xl border py-2.5 text-sm font-medium transition-colors " +
                      (language === lang
                        ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                        : "border-slate-200 text-slate-600 dark:border-slate-800 dark:text-slate-400")
                    }
                  >
                    {lang === "fa" ? "فارسی" : "English"}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="صدا">
              <Select value={effectiveVoiceId} onChange={(e) => setVoiceId(e.target.value)}>
                {voices?.items.length === 0 && <option value="">صدایی در دسترس نیست</option>}
                {voices?.items.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} · {v.gender === "female" ? "زن" : v.gender === "male" ? "مرد" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {selectedVoice && selectedVoice.styles.length > 1 && (
            <Field label="سبک گفتار">
              <div className="flex flex-wrap gap-2">
                {selectedVoice.styles.map((s) => (
                  <button
                    key={s}
                    onClick={() => setStyle(s)}
                    className={
                      "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors " +
                      (style === s
                        ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                        : "border-slate-200 text-slate-500 dark:border-slate-800 dark:text-slate-400")
                    }
                  >
                    {STYLE_LABELS[s]}
                  </button>
                ))}
              </div>
            </Field>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label={`سرعت (${rate.toFixed(2)}×)`}>
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={rate}
                onChange={(e) => setRate(Number(e.target.value))}
                className="w-full accent-brand-600"
              />
            </Field>
            {selectedVoice?.supports_pitch && (
              <Field label={`زیروبمی (${pitch > 0 ? "+" : ""}${pitch})`}>
                <input
                  type="range"
                  min={-12}
                  max={12}
                  step={1}
                  value={pitch}
                  onChange={(e) => setPitch(Number(e.target.value))}
                  className="w-full accent-brand-600"
                />
              </Field>
            )}
          </div>

          <Button onClick={synthesize} loading={runner.isActive} disabled={runner.isActive}>
            <Play size={16} />
            تولید گفتار
          </Button>
        </CardBody>
      </Card>

      {(runner.isActive || runner.job) && (
        <Card>
          <CardHeader
            title="نتیجه"
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

            {output?.asset_id && runner.status === "completed" && (
              <div className="rounded-xl border border-slate-200 p-3.5 dark:border-slate-800">
                <div className="mb-2 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Volume2 size={14} />
                  مدت زمان: <span className="num">{output.duration_display}</span>
                  {output.pause_count ? <span>· {output.pause_count} مکث</span> : null}
                </div>
                <audio controls src={assetUrl(output.asset_id)} className="w-full" />
              </div>
            )}

            <CliConsole lines={runner.logs} height="10rem" />
          </CardBody>
        </Card>
      )}
    </div>
  );
}
