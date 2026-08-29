/**
 * Toast notifications.
 *
 * A minimal global store + host component, avoiding a dependency for
 * something this small. Call `toast.success(...)`, `toast.error(...)` etc.
 * from anywhere; `<ToastHost />` (mounted once in App.tsx) renders them.
 */

import { useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";

type ToastTone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

function push(tone: ToastTone, title: string, description?: string) {
  const id = nextId++;
  items = [...items, { id, tone, title, description }];
  emit();
  setTimeout(() => dismiss(id), 5000);
}

function dismiss(id: number) {
  items = items.filter((item) => item.id !== id);
  emit();
}

export const toast = {
  success: (title: string, description?: string) => push("success", title, description),
  error: (title: string, description?: string) => push("error", title, description),
  info: (title: string, description?: string) => push("info", title, description),
};

const toneStyles: Record<ToastTone, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  error: "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200",
  info: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200",
};

export function ToastHost() {
  const list = useSyncExternalStore(
    (callback) => {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
    () => items,
  );

  if (list.length === 0) return null;

  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[100] flex flex-col items-center gap-2 px-4 sm:bottom-6 sm:items-end sm:px-6">
      {list.map((item) => (
        <div
          key={item.id}
          className={clsx(
            "pointer-events-auto w-full max-w-sm rounded-xl border p-3.5 shadow-lg",
            toneStyles[item.tone],
          )}
          role="alert"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{item.title}</p>
              {item.description && <p className="mt-0.5 text-xs opacity-80">{item.description}</p>}
            </div>
            <button
              onClick={() => dismiss(item.id)}
              className="shrink-0 opacity-60 hover:opacity-100"
              aria-label="بستن پیام"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>
      ))}
    </div>,
    document.body,
  );
}
