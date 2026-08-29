/**
 * Features 3 and 4: AI text editing and translation.
 *
 * The one rule this page exists to enforce: the AI never silently overwrites
 * the user's text. `content` (the editable original) and `result` (what the
 * AI produced) are two separate pieces of state; "Apply" copies the result
 * into the editable original, "Reject" just discards it. Either way nothing
 * is written back to the source document until the user acts.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Check, X, Copy, Sparkles, FileText } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { aiApi, documentsApi, jobsApi } from "@/lib/api/resources";
import { ModelSelector } from "@/components/ai/ModelSelector";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, Textarea, Select, Field, toast } from "@/components/ui";
import type { AITaskType, Language } from "@/lib/api/types";

type Mode = "editing" | "translation" | "custom";

const MODE_TASK: Record<Mode, AITaskType> = {
  editing: "text_editing",
  translation: "translation",
  custom: "general",
};

export function TextEditPage() {
  const { projectId } = useProject();
  const [mode, setMode] = useState<Mode>("editing");
  const [sourceDocId, setSourceDocId] = useState<string>("");
  const [content, setContent] = useState("");
  const [customPrompt, setCustomPrompt] = useState("");
  const [sourceLang, setSourceLang] = useState<Language>("fa");
  const [targetLang, setTargetLang] = useState<Language>("en");
  const [model, setModel] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  // Which built-in prompt (if any) the user picked for editing/translation.
  // A task can have more than one built-in template (e.g. "اصلاح نگارشی" vs
  // "روان‌سازی و بهبود خوانایی" under text_editing); without this the chips
  // were purely decorative - clicking one only showed a toast with its
  // description, the backend always used index 0 regardless of what the
  // user clicked. Selecting one now actually sends that prompt's body.
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);

  const { data: documents } = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => documentsApi.list(projectId),
  });
  const { data: prompts } = useQuery({
    queryKey: ["prompts", MODE_TASK[mode]],
    queryFn: () => aiApi.prompts(MODE_TASK[mode]),
  });
  const selectedPrompt = prompts?.items.find((p) => p.id === selectedPromptId) ?? null;

  const runner = useJobRunner((job) => {
    const text = (job.output as { result?: string }).result ?? "";
    setResult(text);
  }, `cca:job:${projectId}:text_task`);

  const loadDocument = (id: string) => {
    setSourceDocId(id);
    const doc = documents?.items.find((d) => d.id === id);
    if (doc) {
      setContent(doc.content);
      setResult(null);
    }
  };

  const send = () => {
    if (!content.trim()) {
      toast.error("متنی برای پردازش وجود ندارد");
      return;
    }
    setResult(null);
    runner.run(() =>
      jobsApi.processText(projectId, {
        task: MODE_TASK[mode],
        content,
        prompt: mode === "custom" ? customPrompt : selectedPrompt?.body,
        source_language: mode === "translation" ? sourceLang : undefined,
        target_language: mode === "translation" ? targetLang : undefined,
        model: model ?? undefined,
        save: true,
      }),
    );
  };

  const applyResult = () => {
    if (!result) return;
    setContent(result);
    setResult(null);
    toast.success("نتیجه اعمال شد");
  };

  const rejectResult = () => setResult(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">ویرایش و ترجمه متن</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          متن را ویرایش کنید، به هوش مصنوعی بسپارید، نتیجه را بررسی و سپس اعمال یا رد کنید
        </p>
      </div>

      <div className="flex gap-2">
        {(
          [
            { id: "editing", label: "ویرایش متن" },
            { id: "translation", label: "ترجمه" },
            { id: "custom", label: "دستور دلخواه" },
          ] as const
        ).map((m) => (
          <button
            key={m.id}
            onClick={() => {
              setMode(m.id);
              setSelectedPromptId(null);
            }}
            className={
              "rounded-xl border px-4 py-2 text-sm font-medium transition-colors " +
              (mode === m.id
                ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                : "border-slate-200 text-slate-600 hover:border-slate-300 dark:border-slate-800 dark:text-slate-400")
            }
          >
            {m.label}
          </button>
        ))}
      </div>

      {documents && documents.items.length > 0 && (
        <Field label="بارگذاری از سند موجود" hint="اختیاری - یا مستقیماً در کادر زیر بنویسید">
          <Select value={sourceDocId} onChange={(e) => loadDocument(e.target.value)}>
            <option value="">بدون بارگذاری...</option>
            {documents.items.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title || doc.type} (نسخه {doc.version})
              </option>
            ))}
          </Select>
        </Field>
      )}

      {mode === "translation" && (
        <div className="flex items-center gap-3">
          <Select value={sourceLang} onChange={(e) => setSourceLang(e.target.value as Language)} className="flex-1">
            <option value="fa">فارسی</option>
            <option value="en">English</option>
          </Select>
          <ArrowLeftRight size={18} className="shrink-0 text-slate-400" />
          <Select value={targetLang} onChange={(e) => setTargetLang(e.target.value as Language)} className="flex-1">
            <option value="en">English</option>
            <option value="fa">فارسی</option>
          </Select>
        </div>
      )}

      {mode === "custom" && (
        <Field label="دستور شما به هوش مصنوعی" required>
          <Textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            rows={3}
            placeholder="مثلاً: این متن را از نظر نگارشی اصلاح کن. معنی متن را تغییر نده."
          />
        </Field>
      )}

      {mode !== "custom" && prompts && prompts.items.length > 0 && (
        <div>
          <div className="flex flex-wrap gap-1.5">
            {prompts.items.map((p) => {
              const active = selectedPromptId === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => setSelectedPromptId(active ? null : p.id)}
                  title={p.description_fa}
                  aria-pressed={active}
                  className={
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors " +
                    (active
                      ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-950/30 dark:text-brand-300"
                      : "border-slate-200 text-slate-500 hover:border-brand-300 hover:text-brand-600 dark:border-slate-800 dark:text-slate-400")
                  }
                >
                  {p.name_fa}
                </button>
              );
            })}
          </div>
          {selectedPrompt?.description_fa && (
            <p className="mt-1.5 text-xs text-slate-400">{selectedPrompt.description_fa}</p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="متن اصلی" description="قابل ویرایش دستی" />
          <CardBody>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={12}
              placeholder="متن خود را اینجا بنویسید یا از سند موجود بارگذاری کنید..."
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="نتیجه هوش مصنوعی"
            action={
              result && (
                <div className="flex gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(result)}>
                    <Copy size={14} />
                  </Button>
                  <Button size="sm" variant="danger" onClick={rejectResult}>
                    <X size={14} />
                    رد کردن
                  </Button>
                  <Button size="sm" onClick={applyResult}>
                    <Check size={14} />
                    اعمال
                  </Button>
                </div>
              )
            }
          />
          <CardBody>
            {result ? (
              <div className="max-h-[19rem] overflow-y-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3.5 text-sm leading-relaxed text-slate-700 dark:bg-slate-800/40 dark:text-slate-300">
                {result}
              </div>
            ) : (
              <div className="flex h-[19rem] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-200 text-center text-sm text-slate-400 dark:border-slate-800">
                <FileText size={28} className="text-slate-300 dark:text-slate-700" />
                نتیجه پس از اجرا اینجا نمایش داده می‌شود
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardBody className="space-y-4">
          <ModelSelector task={MODE_TASK[mode]} value={model} onChange={setModel} />
          <Button onClick={send} loading={runner.isActive} disabled={runner.isActive || !content.trim()}>
            <Sparkles size={16} />
            ارسال به هوش مصنوعی
          </Button>
          {runner.error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">
              {runner.error}
            </div>
          )}
          {(runner.isActive || runner.logs.length > 0) && <CliConsole lines={runner.logs} height="10rem" />}
        </CardBody>
      </Card>
    </div>
  );
}
