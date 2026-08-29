/**
 * Settings page.
 *
 * One tab per section, mirroring `backend/app/services/settings.py:SECTIONS`
 * exactly, so a new setting added there needs no new frontend section - only
 * a new field in the right tab. Each tab loads its current values from
 * `GET /api/settings`, edits a local draft, and saves via `PUT /api/settings`
 * (which validates server-side and reports back a Persian error on the exact
 * field that failed).
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Save, RotateCcw, FolderOpen, CheckCircle2 } from "lucide-react";
import { settingsApi, aiApi, systemApi } from "@/lib/api/resources";
import { StylePanel } from "@/components/subtitle/StylePanel";
import { FilePickerDialog } from "@/components/media/FilePickerDialog";
import { Tabs, Card, CardBody, Field, Input, Select, Button, toast } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { SubtitleStyle } from "@/lib/api/types";

type Section = "general" | "ai" | "transcription" | "media" | "subtitle" | "voice";

const SECTION_TABS: { id: Section; label: string }[] = [
  { id: "general", label: "عمومی" },
  { id: "ai", label: "هوش مصنوعی" },
  { id: "transcription", label: "تبدیل گفتار به متن" },
  { id: "media", label: "رسانه" },
  { id: "subtitle", label: "زیرنویس" },
  { id: "voice", label: "صدا" },
];

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const section = (params.get("tab") as Section) || "general";
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: settingsApi.get });
  const [draft, setDraft] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (data) setDraft(data.values);
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => settingsApi.update(values),
    onSuccess: (result) => {
      queryClient.setQueryData(["settings"], result);
      toast.success("تنظیمات ذخیره شد");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "خطا در ذخیره تنظیمات"),
  });

  const resetMutation = useMutation({
    mutationFn: () => settingsApi.reset(),
    onSuccess: (result) => {
      queryClient.setQueryData(["settings"], result);
      toast.success("تنظیمات به مقدار پیش‌فرض بازگشت");
    },
  });

  const set = (key: string, value: unknown) => setDraft((prev) => ({ ...prev, [key]: value }));

  const saveSection = (keys: string[]) => {
    const payload: Record<string, unknown> = {};
    for (const key of keys) payload[key] = draft[key];
    saveMutation.mutate(payload);
  };

  if (isLoading || !data) {
    return <p className="text-sm text-slate-400">در حال بارگذاری...</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100 sm:text-2xl">تنظیمات</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            پیکربندی پلتفرم؛ تغییرات بلافاصله اعمال می‌شوند
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (confirm("همه تنظیمات به مقدار پیش‌فرض بازگردانده شوند؟")) resetMutation.mutate();
          }}
        >
          <RotateCcw size={14} />
          بازگشت به پیش‌فرض
        </Button>
      </div>

      <Card>
        <Tabs tabs={SECTION_TABS} active={section} onChange={(id) => setParams({ tab: id })} />
        <CardBody>
          {section === "general" && <GeneralSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />}
          {section === "ai" && <AiSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />}
          {section === "transcription" && (
            <TranscriptionSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />
          )}
          {section === "media" && <MediaSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />}
          {section === "subtitle" && <SubtitleSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />}
          {section === "voice" && <VoiceSection draft={draft} set={set} onSave={saveSection} saving={saveMutation.isPending} />}
        </CardBody>
      </Card>
    </div>
  );
}

interface SectionProps {
  draft: Record<string, unknown>;
  set: (key: string, value: unknown) => void;
  onSave: (keys: string[]) => void;
  saving: boolean;
}

function SaveBar({ onSave, keys, saving }: { onSave: (keys: string[]) => void; keys: string[]; saving: boolean }) {
  return (
    <Button onClick={() => onSave(keys)} loading={saving}>
      <Save size={15} />
      ذخیره تغییرات
    </Button>
  );
}

function GeneralSection({ draft, set, onSave, saving }: SectionProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const keys = ["general.workspace_dir", "general.max_import_size_mb", "general.theme"];
  return (
    <div className="space-y-4">
      <Field label="پوشه کارگاه" hint="محل ذخیره‌سازی پروژه‌ها">
        <div className="flex gap-2">
          <Input ltr value={String(draft["general.workspace_dir"] ?? "")} readOnly className="flex-1" />
          <Button variant="outline" onClick={() => setPickerOpen(true)}>
            <FolderOpen size={15} />
          </Button>
        </div>
      </Field>
      <Field label="حداکثر حجم فایل ورودی (مگابایت)">
        <Input
          ltr
          type="number"
          value={Number(draft["general.max_import_size_mb"] ?? 0)}
          onChange={(e) => set("general.max_import_size_mb", Number(e.target.value))}
        />
      </Field>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
      <FilePickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={() => toast.info("انتخاب پوشه از طریق مسیر فایل امکان‌پذیر است")}
      />
    </div>
  );
}

/** Path-setting key and placeholder per provider - grows by one line per new provider. */
const PROVIDER_CLI_PATH_KEY: Record<string, { key: string; placeholder: string; install: string }> = {
  claude: {
    key: "ai.claude_cli_path",
    placeholder: "C:\\Users\\...\\claude.exe",
    install: "نصب: راهنمای Claude Code را در claude.com/claude-code ببینید",
  },
  codex: {
    key: "ai.codex_cli_path",
    placeholder: "C:\\Users\\...\\npm\\codex.cmd",
    install: "نصب: npm install -g @openai/codex",
  },
};

function AiSection({ draft, set, onSave, saving }: SectionProps) {
  const { data: providers } = useQuery({ queryKey: ["providers"], queryFn: () => aiApi.providers(true) });
  const selectedProvider = String(draft["ai.provider"] ?? "claude");
  const { data: models } = useQuery({
    queryKey: ["models", selectedProvider],
    queryFn: () => aiApi.models({ provider: selectedProvider }),
  });
  const keys = [
    "ai.provider",
    "ai.claude_cli_path",
    "ai.codex_cli_path",
    "ai.default_model",
    "ai.timeout_seconds",
  ];
  const active = providers?.items.find((p) => p.id === selectedProvider);

  // Switching provider changes which model list is valid, so the previously
  // saved default model (from the other provider) would silently point at a
  // nonexistent id - reset it to the new provider's own default the moment
  // the switch happens, and again once its model list has loaded.
  const selectProvider = (providerId: string) => {
    set("ai.provider", providerId);
    set("ai.default_model", "");
  };

  return (
    <div className="space-y-4">
      <Field
        label="ارائه‌دهنده هوش مصنوعی"
        hint="این ارائه‌دهنده برای ویرایش متن، ترجمه و بازبینی رونوشت استفاده می‌شود؛ در هر صفحه نیز قابل تغییر موردی است"
      >
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {providers?.items.map((p) => {
            const isSelected = selectedProvider === p.id;
            return (
              <button
                key={p.id}
                onClick={() => selectProvider(p.id)}
                className={
                  "flex items-center justify-between rounded-xl border p-3 text-start transition-colors " +
                  (isSelected
                    ? "border-brand-500 bg-brand-50 dark:border-brand-600 dark:bg-brand-950/30"
                    : "border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700")
                }
              >
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{p.display_name}</p>
                  <p
                    className={
                      "mt-0.5 text-xs " +
                      (p.available ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400 dark:text-slate-500")
                    }
                  >
                    {p.available ? `متصل${p.version ? ` · ${p.version}` : ""}` : "در دسترس نیست"}
                  </p>
                </div>
                {isSelected && <CheckCircle2 size={18} className="shrink-0 text-brand-600 dark:text-brand-400" />}
              </button>
            );
          })}
        </div>
      </Field>

      {active && (
        <div
          className={
            "rounded-xl p-3.5 text-sm " +
            (active.available
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
              : "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300")
          }
        >
          {active.available
            ? `${active.display_name} متصل و آماده است.`
            : active.unavailable_reason ?? "این ارائه‌دهنده در دسترس نیست."}
          {!active.available && PROVIDER_CLI_PATH_KEY[selectedProvider] && (
            <p className="mt-1 text-xs opacity-80">{PROVIDER_CLI_PATH_KEY[selectedProvider].install}</p>
          )}
        </div>
      )}

      <div className="space-y-3 border-t border-slate-100 pt-4 dark:border-slate-800">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">مسیر ابزارهای خط فرمان</p>
        {Object.entries(PROVIDER_CLI_PATH_KEY).map(([providerId, cfg]) => {
          const info = providers?.items.find((p) => p.id === providerId);
          return (
            <Field
              key={providerId}
              label={`مسیر ${info?.display_name ?? providerId} CLI`}
              hint="در صورت خالی بودن، به‌صورت خودکار جستجو می‌شود"
            >
              <Input
                ltr
                value={String(draft[cfg.key] ?? "")}
                onChange={(e) => set(cfg.key, e.target.value)}
                placeholder={cfg.placeholder}
              />
            </Field>
          );
        })}
      </div>

      <Field label={`مدل پیش‌فرض (${active?.display_name ?? selectedProvider})`}>
        <Select value={String(draft["ai.default_model"] ?? "")} onChange={(e) => set("ai.default_model", e.target.value)}>
          <option value="">استفاده از پیشنهاد خودکار برای هر کار</option>
          {models?.items.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="زمان انتظار (ثانیه)">
        <Input
          ltr
          type="number"
          value={Number(draft["ai.timeout_seconds"] ?? 900)}
          onChange={(e) => set("ai.timeout_seconds", Number(e.target.value))}
        />
      </Field>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
    </div>
  );
}

function TranscriptionSection({ draft, set, onSave, saving }: SectionProps) {
  const { data: engines } = useQuery({ queryKey: ["transcriptionEngines"], queryFn: () => aiApi.transcriptionEngines(true) });
  const engine = engines?.items[0];
  const keys = ["transcription.model_size", "transcription.vad_filter", "transcription.auto_refine"];

  return (
    <div className="space-y-4">
      {engine && (
        <div
          className={
            "rounded-xl p-3.5 text-sm " +
            (engine.available
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
              : "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300")
          }
        >
          {engine.available ? `موتور ${engine.display_name} فعال است` : `${engine.unavailable_reason} ${engine.hint ?? ""}`}
        </div>
      )}
      <Field label="اندازه مدل" hint="مدل بزرگ‌تر دقیق‌تر اما کندتر است">
        <Select value={String(draft["transcription.model_size"] ?? "small")} onChange={(e) => set("transcription.model_size", e.target.value)}>
          {engine?.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label_fa} ({m.size_mb} مگابایت){m.downloaded ? " ✓" : ""}
            </option>
          ))}
        </Select>
      </Field>
      <label className="flex items-center gap-2.5 text-sm text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          checked={Boolean(draft["transcription.vad_filter"])}
          onChange={(e) => set("transcription.vad_filter", e.target.checked)}
          className="h-4 w-4 rounded border-slate-300 text-brand-600"
        />
        حذف خودکار سکوت‌های طولانی
      </label>
      <label className="flex items-center gap-2.5 text-sm text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          checked={Boolean(draft["transcription.auto_refine"])}
          onChange={(e) => set("transcription.auto_refine", e.target.checked)}
          className="h-4 w-4 rounded border-slate-300 text-brand-600"
        />
        بازبینی خودکار با هوش مصنوعی پس از تبدیل
      </label>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
    </div>
  );
}

function MediaSection({ draft, set, onSave, saving }: SectionProps) {
  const { data: media } = useQuery({ queryKey: ["mediaCapabilities"], queryFn: systemApi.media });
  const keys = ["media.ffmpeg_path", "media.audio_preset", "media.render_quality"];

  return (
    <div className="space-y-4">
      <div
        className={
          "rounded-xl p-3.5 text-sm " +
          (media?.ffmpeg_available
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
            : "bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300")
        }
      >
        {media?.ffmpeg_available ? `FFmpeg فعال است (${media.ffmpeg_version})` : "FFmpeg پیدا نشد"}
      </div>
      <Field label="مسیر FFmpeg" hint="در صورت خالی بودن، نسخه همراه برنامه استفاده می‌شود">
        <Input ltr value={String(draft["media.ffmpeg_path"] ?? "")} onChange={(e) => set("media.ffmpeg_path", e.target.value)} />
      </Field>
      <Field label="پیش‌فرض کیفیت صدا">
        <Select value={String(draft["media.audio_preset"] ?? "opus")} onChange={(e) => set("media.audio_preset", e.target.value)}>
          {media?.audio_presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label_fa}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="پیش‌فرض کیفیت رندر">
        <Select value={String(draft["media.render_quality"] ?? "balanced")} onChange={(e) => set("media.render_quality", e.target.value)}>
          {media?.render_qualities.map((q) => (
            <option key={q.id} value={q.id}>
              {q.label_fa}
            </option>
          ))}
        </Select>
      </Field>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
    </div>
  );
}

function SubtitleSection({ draft, set, onSave, saving }: SectionProps) {
  const style = (draft["subtitle.style"] as SubtitleStyle) ?? undefined;
  const keys = ["subtitle.style", "subtitle.export_format"];

  if (!style) return null;

  return (
    <div className="space-y-4">
      <StylePanel style={style} onChange={(patch) => set("subtitle.style", { ...style, ...patch })} />
      <Field label="قالب پیش‌فرض خروجی">
        <Select value={String(draft["subtitle.export_format"] ?? "srt")} onChange={(e) => set("subtitle.export_format", e.target.value)}>
          <option value="srt">SRT</option>
          <option value="vtt">WebVTT</option>
          <option value="ass">ASS</option>
        </Select>
      </Field>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
    </div>
  );
}

function VoiceSection({ draft, set, onSave, saving }: SectionProps) {
  const language = String(draft["voice.language"] ?? "fa") as "fa" | "en";
  const { data: voices } = useQuery({ queryKey: ["voices", language], queryFn: () => aiApi.voices({ language }) });
  const keys = ["voice.language", "voice.voice_id", "voice.rate", "voice.output_format"];

  return (
    <div className="space-y-4">
      <Field label="زبان پیش‌فرض">
        <Select value={language} onChange={(e) => set("voice.language", e.target.value)}>
          <option value="fa">فارسی</option>
          <option value="en">English</option>
        </Select>
      </Field>
      <Field label="صدای پیش‌فرض">
        <Select value={String(draft["voice.voice_id"] ?? "")} onChange={(e) => set("voice.voice_id", e.target.value)}>
          {voices?.items.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="قالب خروجی">
        <Select value={String(draft["voice.output_format"] ?? "mp3")} onChange={(e) => set("voice.output_format", e.target.value)}>
          <option value="mp3">MP3</option>
          <option value="wav">WAV</option>
        </Select>
      </Field>
      <SaveBar onSave={onSave} keys={keys} saving={saving} />
    </div>
  );
}
