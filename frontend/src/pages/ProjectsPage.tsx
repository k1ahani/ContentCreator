import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Folder, Trash2, MoreVertical } from "lucide-react";
import { projectsApi } from "@/lib/api/resources";
import {
  Button,
  Card,
  CardBody,
  Dialog,
  Field,
  Input,
  Textarea,
  EmptyState,
  Skeleton,
  toast,
} from "@/components/ui";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { ApiError } from "@/lib/api/client";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: () => projectsApi.create({ name: name.trim(), description: description.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setCreateOpen(false);
      setName("");
      setDescription("");
      toast.success("پروژه ساخته شد");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "خطا در ساخت پروژه"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success("پروژه حذف شد");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "خطا در حذف پروژه"),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100 sm:text-2xl">پروژه‌ها</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            هر پروژه یک جریان کار مستقل از ویدیو تا زیرنویس و صدا است
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus size={16} />
          پروژه جدید
        </Button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<Folder size={40} />}
          title="هنوز پروژه‌ای وجود ندارد"
          description="برای شروع، یک پروژه جدید بسازید."
          action={<Button onClick={() => setCreateOpen(true)}>ساخت پروژه جدید</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((project) => (
            <Card key={project.id} className="relative overflow-visible">
              <Link to={`/projects/${project.id}`} className="block">
                <CardBody>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-400">
                      <Folder size={18} />
                    </div>
                  </div>
                  <h3 className="mt-3 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {project.name}
                  </h3>
                  {project.description && (
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
                      {project.description}
                    </p>
                  )}
                  <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
                    <span>{formatNumber(project.asset_count)} فایل</span>
                    <span>{formatNumber(project.document_count)} سند</span>
                    <span className="me-auto">{formatRelativeTime(project.updated_at)}</span>
                  </div>
                </CardBody>
              </Link>
              <button
                onClick={(e) => {
                  e.preventDefault();
                  setOpenMenuId(openMenuId === project.id ? null : project.id);
                }}
                className="absolute end-3 top-3 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="گزینه‌های بیشتر"
              >
                <MoreVertical size={16} />
              </button>
              {openMenuId === project.id && (
                <div className="absolute end-3 top-11 z-10 w-40 rounded-xl border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  <button
                    onClick={() => {
                      setOpenMenuId(null);
                      if (confirm(`پروژه «${project.name}» حذف شود؟ فایل‌های آن نگه داشته می‌شوند.`)) {
                        deleteMutation.mutate(project.id);
                      }
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-xs text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/50"
                  >
                    <Trash2 size={14} />
                    حذف پروژه
                  </button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="ساخت پروژه جدید"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              انصراف
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              loading={createMutation.isPending}
              disabled={!name.trim()}
            >
              ساخت پروژه
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="نام پروژه" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً: آموزش React" autoFocus />
          </Field>
          <Field label="توضیحات" hint="اختیاری">
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="توضیح مختصری درباره این پروژه"
            />
          </Field>
        </div>
      </Dialog>
    </div>
  );
}
