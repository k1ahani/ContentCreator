import { NavLink, Outlet, useParams, useNavigate } from "react-router-dom";
import { ArrowRight, Menu } from "lucide-react";
import clsx from "clsx";
import { PROJECT_NAVIGATION } from "@/components/layout/navigation";
import { useProject } from "@/hooks/useProject";
import { useUIStore } from "@/store/uiStore";
import { Skeleton } from "@/components/ui";
import { useEventConnectionStatus } from "@/lib/api/events";

export function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading } = useProject();
  const navigate = useNavigate();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  useEventConnectionStatus(); // ensures the SSE connection opens as soon as a project is entered

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-[rgb(10,12,18)]">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            <button
              onClick={toggleSidebar}
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden"
            >
              <Menu size={20} />
            </button>
            <button
              onClick={() => navigate("/projects")}
              className="flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <ArrowRight size={16} />
              پروژه‌ها
            </button>
            <span className="text-slate-300 dark:text-slate-700">/</span>
            {isLoading ? (
              <Skeleton className="h-5 w-32" />
            ) : (
              <h1 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100 sm:text-base">
                {project?.name}
              </h1>
            )}
          </div>
          <nav className="scrollbar-none flex gap-1 overflow-x-auto px-4 pb-1 sm:px-6">
            {PROJECT_NAVIGATION.map((item) => (
              <NavLink
                key={item.path}
                to={`/projects/${projectId}/${item.path}`}
                end={item.path === ""}
                className={({ isActive }) =>
                  clsx(
                    "relative flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-2.5 text-xs font-medium transition-colors sm:text-sm",
                    isActive
                      ? "text-brand-600 dark:text-brand-400"
                      : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <item.icon size={15} />
                    {item.label}
                    {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-600" />}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
