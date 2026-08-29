/**
 * Sidebar: static rail on desktop, slide-in drawer on mobile.
 *
 * On mobile it becomes an overlay drawer (per requirement 3: "sidebar becomes
 * a mobile drawer"), driven by `uiStore.sidebarOpen` and closed on navigation
 * or backdrop tap.
 */

import { NavLink, useLocation } from "react-router-dom";
import { useEffect } from "react";
import clsx from "clsx";
import { Sparkles } from "lucide-react";
import { NAVIGATION } from "./navigation";
import { useUIStore } from "@/store/uiStore";

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
      {NAVIGATION.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
            )
          }
        >
          <item.icon size={18} strokeWidth={2} className="shrink-0" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Sidebar() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);
  const location = useLocation();

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname, setSidebarOpen]);

  return (
    <>
      {/* Desktop rail */}
      <aside className="hidden w-64 shrink-0 flex-col border-l border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:flex">
        <Brand />
        <NavList />
      </aside>

      {/* Mobile drawer */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-slate-950/50"
            onClick={() => setSidebarOpen(false)}
          />
          <aside className="absolute inset-y-0 right-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-xl dark:bg-slate-900">
            <Brand />
            <NavList onNavigate={() => setSidebarOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}

function Brand() {
  return (
    <div className="flex h-16 shrink-0 items-center gap-2.5 border-b border-slate-200 px-5 dark:border-slate-800">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white">
        <Sparkles size={18} />
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">
          پلتفرم تولید محتوا
        </p>
        <p className="truncate text-[11px] text-slate-400">نسخه محلی</p>
      </div>
    </div>
  );
}
