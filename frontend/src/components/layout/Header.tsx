import { Menu, Sun, Moon, Monitor, Circle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useUIStore } from "@/store/uiStore";
import { systemApi } from "@/lib/api/resources";
import { useEventConnectionStatus } from "@/lib/api/events";

export function Header({ title }: { title?: string }) {
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);
  const connected = useEventConnectionStatus();

  const { data: status } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: systemApi.status,
    refetchInterval: 30_000,
  });

  const nextTheme = { light: "dark", dark: "system", system: "light" } as const;
  const themeIcon = { light: Sun, dark: Moon, system: Monitor }[theme];
  const ThemeIcon = themeIcon;

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80 sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={toggleSidebar}
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden"
          aria-label="باز کردن منو"
        >
          <Menu size={20} />
        </button>
        {title && <h1 className="truncate text-base font-semibold text-slate-900 dark:text-slate-100 sm:text-lg">{title}</h1>}
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {status && !status.ready && (
          <span className="hidden items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-700 dark:bg-amber-950 dark:text-amber-400 sm:flex">
            <Circle size={8} className="fill-current" />
            نیازمند بررسی وابستگی‌ها
          </span>
        )}
        <span
          className="hidden items-center gap-1.5 text-xs text-slate-400 sm:flex"
          title={connected ? "اتصال زنده برقرار است" : "در حال اتصال..."}
        >
          <Circle size={8} className={connected ? "fill-emerald-500 text-emerald-500" : "fill-slate-300 text-slate-300"} />
        </span>
        <button
          onClick={() => setTheme(nextTheme[theme])}
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          aria-label="تغییر پوسته"
          title="تغییر پوسته"
        >
          <ThemeIcon size={18} />
        </button>
      </div>
    </header>
  );
}
