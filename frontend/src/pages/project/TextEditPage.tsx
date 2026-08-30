/**
 * Features 3 and 4: AI text editing and translation.
 *
 * The one rule this page exists to enforce: the AI never silently overwrites
 * the user's text. `content` (the editable original) and `result` (what the
 * AI produced) are two separate pieces of state; "Apply" copies the result
 * into the editable original, "Reject" just discards it. Either way nothing
 * is written back to the source document until the user acts.
 *
 * **The AI is optional here, not required.** The result box is a real
 * textarea, not a read-only panel: the user can paste a translation they
 * produced elsewhere, fix what the model got wrong, or type the whole thing
 * by hand, and then apply or save it exactly as if the AI had produced it.
 * That matters because the AI providers are CLIs talking to remote services -
 * on a network where those are blocked, a read-only result box would make the
 * entire page useless, when the only part that actually needed the network
 * was one optional step in the middle.
 *
 * "ذخیره به‌عنوان سند" is what makes the manual path complete: it turns
 * whatever is in the result box into a new `TextDocument` that continues the
 * source document's version chain, so a hand-made translation is a first-class
 * version of the text rather than something stranded in a textarea.
 */

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Check, X, Copy, Sparkles, ClipboardPaste, Save } from "lucide-react";
import { useProject } from "@/hooks/useProject";
import { useJobRunner } from "@/hooks/useJobRunner";
import { aiApi, documentsApi, jobsApi, settingsApi } from "@/lib/api/resources";
import { ModelSelector } from "@/components/ai/ModelSelector";
import { CliConsole } from "@/components/console/CliConsole";
import { Card, CardHeader, CardBody, Button, Textarea, Select, Field, toast } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { AITaskType, DocumentType, Language } from "@/lib/api/types";

type Mode = "editing" | "translation" | "custom";

const MODE_TASK: Record<Mode, AITaskType> = {
  editing: "text_editing",
  translation: "translation",
  custom: "general",
};

/** Where a saved result lands in the document list, per mode. */
const MODE_DOCUMENT_TYPE: Record<Mode, DocumentType> = {
  editing: "edited",
  translation: "translation",
  custom: "edited",
};

/**
 * Setting holding the user's last custom instruction.
 *
 * A setting rather than a saved-prompt row because of what the requirement
 * actually asks for: one instruction that follows the user into their *next*
 * project and is pre-filled there. That is a single global "what I was last
 * doing" value, not a named template in a library the user curates - the
 * prompts table already exists for the latter.
 */
const CUSTOM_PROMPT_SETTING = "ai.custom_prompt";

/**
 * Pseudo-id for the "custom instruction" chip that sits alongside the
 * built-in prompts (proofreading, tone adjustment, ...). Selecting it swaps
 * the built-in body for the user's own persisted instruction, so a custom
 * prompt is available in every mode rather than only in the standalone
 * custom mode.
 */
const CUSTOM_PROMPT_ID = "__custom__";

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
  const [savingDocument, setSavingDocument] = useState(false);
  const queryClient = useQueryClient();

  const { data: documents } = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => documentsApi.list(projectId),
  });
  const { data: prompts } = useQuery({
    queryKey: ["prompts", MODE_TASK[mode]],
    queryFn: () => aiApi.prompts(MODE_TASK[mode]),
  });
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => settingsApi.get(),
  });

  const sourceDocument = documents?.items.find((d) => d.id === sourceDocId) ?? null;
  const usingCustomPrompt = mode === "custom" || selectedPromptId === CUSTOM_PROMPT_ID;
  const selectedPrompt =
    selectedPromptId === CUSTOM_PROMPT_ID
      ? null
      : prompts?.items.find((p) => p.id === selectedPromptId) ?? null;

  // Pre-fill the custom instruction with whatever the user last saved -
  // including in a project they have never opened before, which is the point
  // of storing it as a setting. Only fills an empty box, so it can never
  // clobber something the user is in the middle of typing.
  useEffect(() => {
    const stored = settings?.values?.[CUSTOM_PROMPT_SETTING];
    if (typeof stored === "string" && stored.trim()) {
      setCustomPrompt((current) => (current.trim() ? current : stored));
    }
  }, [settings]);

  /**
   * Persist the custom instruction so the next project starts from it.
   *
   * Fire-and-forget: this is a convenience, and a failed write must never
   * block the user's actual request from being sent.
   */
  const rememberCustomPrompt = (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed || trimmed === settings?.values?.[CUSTOM_PROMPT_SETTING]) return;
    settingsApi
      .update({ [CUSTOM_PROMPT_SETTING]: trimmed })
      .then(() => queryClient.invalidateQueries({ queryKey: ["settings"] }))
      .catch(() => {
        /* a prompt that failed to save is not worth interrupting the run */
      });
  };

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
    if (usingCustomPrompt && !customPrompt.trim()) {
      toast.error("دستور دلخواه را بنویسید");
      return;
    }
    if (usingCustomPrompt) rememberCustomPrompt(customPrompt);

    setResult(null);
    runner.run(() =>
      jobsApi.processText(projectId, {
        task: MODE_TASK[mode],
        content,
        prompt: usingCustomPrompt ? customPrompt : selectedPrompt?.body,
        source_language: mode === "translation" ? sourceLang : undefined,
        target_language: mode === "translation" ? targetLang : undefined,
        model: model ?? undefined,
        save: true,
      }),
    );
  };

  const applyResult = () => {
    if (!result?.trim()) return;
    setContent(result);
    setResult(null);
    toast.success("نتیجه اعمال شد");
  };

  const rejectResult = () => setResult(null);

  /** Paste the clipboard into the result box - the manual translation path. */
  const pasteIntoResult = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        toast.error("کلیپ‌بورد خالی است");
        return;
      }
      setResult(text);
    } catch {
      // Clipboard read needs a permission the browser may refuse. The
      // textarea still accepts a normal Ctrl+V, so this is a shortcut
      // failing, not the workflow failing - say exactly that.
      toast.error("دسترسی به کلیپ‌بورد ممکن نشد؛ داخل کادر نتیجه از Ctrl+V استفاده کنید");
    }
  };

  /**
   * Save whatever is in the result box as a new document version.
   *
   * Deliberately independent of whether the AI produced that text: this is
   * the step that lets a hand-written or pasted translation become a real
   * version in the document chain, so the rest of the pipeline (subtitles,
   * speech) can consume it like any other.
   */
  const saveResultAsDocument = async () => {
    if (!result?.trim()) return;
    setSavingDocument(true);
    try {
      const created = await documentsApi.create(projectId, {
        type: MODE_DOCUMENT_TYPE[mode],
        title: sourceDocument
          ? `${sourceDocument.title || sourceDocument.type} - ویرایش دستی`
          : "متن ویرایش‌شده",
        content: result,
        language: mode === "translation" ? targetLang : sourceDocument?.language,
        // Continuing the source's chain is what makes the version number in
        // the document list mean something - see docs/TEXT_PROCESSING.md.
        source_document_id: sourceDocId || undefined,
      });
      queryClient.invalidateQueries({ queryKey: ["documents", projectId] });
      toast.success(`ذخیره شد (نسخه ${created.version})`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "ذخیره سند ناموفق بود");
    } finally {
      setSavingDocument(false);
    }
  };

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

      {usingCustomPrompt && (
        <Field
          label="دستور شما به هوش مصنوعی"
          required
          hint="این دستور ذخیره می‌شود و دفعه بعد - حتی در پروژه‌ای دیگر - همین‌جا آماده است."
        >
          <Textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            onBlur={() => rememberCustomPrompt(customPrompt)}
            rows={3}
            placeholder="مثلاً: این متن را از نظر نگارشی اصلاح کن. معنی متن را تغییر نده."
          />
        </Field>
      )}

      {mode !== "custom" && prompts && prompts.items.length > 0 && (
        <div>
          <div className="flex flex-wrap gap-1.5">
            {/*
              The built-in templates for this task (proofreading, tone
              adjustment, ...) plus one more chip for the user's own saved
              instruction, so a custom prompt is reachable from every mode
              rather than only from the standalone custom mode.
            */}
            {[
              ...prompts.items,
              { id: CUSTOM_PROMPT_ID, name_fa: "دستور دلخواه", description_fa: "دستور ذخیره‌شده خودتان" },
            ].map((p) => {
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
            title="نتیجه"
            description="خروجی هوش مصنوعی - یا متنی که خودتان اینجا می‌نویسید یا جای‌گذاری می‌کنید"
            action={
              <div className="flex gap-1.5">
                <Button size="sm" variant="ghost" onClick={pasteIntoResult} title="جای‌گذاری از کلیپ‌بورد">
                  <ClipboardPaste size={14} />
                </Button>
                {result?.trim() && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigator.clipboard.writeText(result)}
                      title="کپی"
                    >
                      <Copy size={14} />
                    </Button>
                    <Button size="sm" variant="danger" onClick={rejectResult}>
                      <X size={14} />
                      پاک کردن
                    </Button>
                    <Button size="sm" onClick={applyResult}>
                      <Check size={14} />
                      اعمال
                    </Button>
                  </>
                )}
              </div>
            }
          />
          <CardBody className="space-y-3">
            {/*
              A textarea, not a read-only panel. This is what lets the whole
              page work with no AI at all: paste a translation produced
              elsewhere, correct what the model got wrong, or write it by
              hand - then apply or save it exactly as if it had come from the
              AI. See the file header.
            */}
            <Textarea
              value={result ?? ""}
              onChange={(e) => setResult(e.target.value)}
              rows={12}
              placeholder="نتیجه هوش مصنوعی اینجا نمایش داده می‌شود - یا متن ترجمه/ویرایش‌شده خود را مستقیماً اینجا بنویسید یا جای‌گذاری کنید..."
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={saveResultAsDocument}
                loading={savingDocument}
                disabled={!result?.trim() || savingDocument}
              >
                <Save size={14} />
                ذخیره به‌عنوان سند
              </Button>
              <span className="text-xs text-slate-400">
                نسخه جدیدی از متن می‌سازد که در بقیه بخش‌ها (زیرنویس و گفتار) قابل استفاده است
              </span>
            </div>
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
