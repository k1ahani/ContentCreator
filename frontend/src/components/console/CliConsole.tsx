/**
 * Live CLI console.
 *
 * Renders the stdout/stderr/system lines a job produces (FFmpeg output,
 * Claude CLI activity, ...). Technical content, so it is always LTR/monospace
 * even though it sits inside the RTL page - this is exactly the case
 * docs/RTL_UI_GUIDELINES.md calls out for `.ltr` treatment.
 */

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import type { JobLogLine } from "@/lib/api/types";

const streamColor: Record<JobLogLine["stream"], string> = {
  stdout: "text-slate-300",
  stderr: "text-amber-400",
  system: "text-sky-400",
};

export function CliConsole({
  lines,
  title = "کنسول هوش مصنوعی",
  height = "16rem",
  autoScroll = true,
}: {
  lines: JobLogLine[];
  title?: string;
  height?: string;
  autoScroll?: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (autoScroll && pinned && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, autoScroll, pinned]);

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-3.5 py-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-xs font-medium text-slate-300">{title}</span>
        </div>
        <span className="ltr text-xs text-slate-500">{lines.length} خط</span>
      </div>
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
        }}
        className="ltr overflow-y-auto p-3.5 font-mono text-xs leading-relaxed"
        style={{ height }}
      >
        {lines.length === 0 ? (
          <p className="text-slate-600">در انتظار شروع اجرا...</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={clsx("whitespace-pre-wrap break-all", streamColor[line.stream])}>
              {line.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
