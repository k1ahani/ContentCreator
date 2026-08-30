/**
 * Voice selection with audible previews.
 *
 * A dropdown of forty names is not a choice, it is a guess. This component
 * exists so the user can *hear* each voice before committing to a synthesis
 * run, which is the only way the choice is real.
 *
 * Playback deliberately uses one shared `<audio>` element rather than one per
 * row. Two reasons: starting a second preview must stop the first (two voices
 * talking over each other is useless), and a single element makes that the
 * default behaviour rather than something to coordinate across N components.
 *
 * The preview URL is handed to the browser as a plain `src` instead of being
 * fetched into a blob here, so the element streams it and honours the
 * endpoint's cache headers - a voice auditioned twice costs one request.
 *
 * Nothing here names a provider. Providers, their availability, their pricing
 * and their voices all arrive from `/api/ai/tts/*`, so a provider added on the
 * backend appears in this list with no change to this file (docs/TTS_SYSTEM.md).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Pause, Play, Volume2 } from "lucide-react";
import clsx from "clsx";
import { aiApi } from "@/lib/api/resources";
import { Badge, Field, Select, toast } from "@/components/ui";
import type { TTSProviderInfo, VoiceSpec } from "@/lib/api/types";

const GENDER_LABELS: Record<string, string> = {
  female: "زن",
  male: "مرد",
  unknown: "",
};

const PRICING_LABELS: Record<TTSProviderInfo["pricing"], { label: string; tone: "success" | "info" | "warning" }> = {
  free: { label: "رایگان", tone: "success" },
  freemium: { label: "رایگان با محدودیت", tone: "info" },
  paid: { label: "پولی", tone: "warning" },
};

export function VoicePicker({
  voices,
  providers,
  selectedVoiceId,
  onSelect,
}: {
  voices: VoiceSpec[];
  providers: TTSProviderInfo[];
  selectedVoiceId: string;
  onSelect: (voiceId: string) => void;
}) {
  const [providerFilter, setProviderFilter] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // A single element for the whole list; see the module comment.
  useEffect(() => {
    const audio = new Audio();
    audio.addEventListener("ended", () => setPlaying(null));
    audio.addEventListener("playing", () => setLoadingPreview(null));
    audioRef.current = audio;
    return () => {
      audio.pause();
      audio.src = "";
      audioRef.current = null;
    };
  }, []);

  const providerNames = useMemo(
    () => Object.fromEntries(providers.map((p) => [p.id, p.display_name])),
    [providers],
  );
  const providerPricing = useMemo(
    () => Object.fromEntries(providers.map((p) => [p.id, p.pricing])),
    [providers],
  );

  const availableProviders = providers.filter((p) => p.available);
  const shown = providerFilter
    ? voices.filter((voice) => voice.provider === providerFilter)
    : voices;

  const play = (voice: VoiceSpec) => {
    const audio = audioRef.current;
    if (!audio) return;

    if (playing === voice.id) {
      audio.pause();
      setPlaying(null);
      return;
    }

    audio.pause();
    setLoadingPreview(voice.id);
    setPlaying(voice.id);
    audio.src = aiApi.voicePreviewUrl(voice.id);
    audio.play().catch(() => {
      // A preview failing is a minor inconvenience, not a broken page: the
      // provider may be offline or out of quota. Say so and move on - the
      // voice itself stays selectable.
      setPlaying(null);
      setLoadingPreview(null);
      toast.error("پخش نمونه این صدا ممکن نشد");
    });
  };

  return (
    <div className="space-y-3">
      {availableProviders.length > 1 && (
        <Field label="ارائه‌دهنده صدا" hint="برای دیدن همه صداها این فیلتر را روی «همه» بگذارید">
          <Select value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
            <option value="">همه ارائه‌دهندگان</option>
            {availableProviders.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.display_name} ({provider.voice_count} صدا)
              </option>
            ))}
          </Select>
        </Field>
      )}

      <div className="max-h-80 space-y-1.5 overflow-y-auto rounded-xl border border-slate-200 p-1.5 dark:border-slate-800">
        {shown.length === 0 && (
          <p className="p-6 text-center text-sm text-slate-400">
            صدایی برای این زبان و ارائه‌دهنده در دسترس نیست
          </p>
        )}

        {shown.map((voice) => {
          const selected = voice.id === selectedVoiceId;
          const gender = GENDER_LABELS[voice.gender] ?? "";
          const pricing = providerPricing[voice.provider];
          return (
            <div
              key={voice.id}
              className={clsx(
                "flex items-start gap-2 rounded-xl border p-2.5 transition-colors",
                selected
                  ? "border-brand-500 bg-brand-50 dark:border-brand-600 dark:bg-brand-950/30"
                  : "border-transparent hover:bg-slate-50 dark:hover:bg-slate-800/50",
              )}
            >
              <button
                type="button"
                onClick={() => play(voice)}
                title="پخش نمونه صدا"
                aria-label={`پخش نمونه صدای ${voice.name}`}
                className={clsx(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
                  playing === voice.id
                    ? "bg-brand-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700",
                )}
              >
                {loadingPreview === voice.id ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : playing === voice.id ? (
                  <Pause size={14} />
                ) : (
                  <Play size={14} />
                )}
              </button>

              <button
                type="button"
                onClick={() => onSelect(voice.id)}
                className="min-w-0 flex-1 text-start"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                    {voice.name}
                  </span>
                  {gender && <Badge tone="neutral">{gender}</Badge>}
                  {voice.locale && (
                    <span className="ltr text-[11px] text-slate-400">{voice.locale}</span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <span>{providerNames[voice.provider] ?? voice.provider}</span>
                  {pricing && pricing !== "free" && (
                    <Badge tone={PRICING_LABELS[pricing].tone}>{PRICING_LABELS[pricing].label}</Badge>
                  )}
                </div>
                {voice.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-400">{voice.description}</p>
                )}
              </button>

              {selected && (
                <Volume2 size={15} className="mt-1.5 shrink-0 text-brand-600 dark:text-brand-400" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
