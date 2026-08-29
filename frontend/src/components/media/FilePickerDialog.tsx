/**
 * Local filesystem picker.
 *
 * A browser cannot hand a web page a real filesystem path from its native
 * file dialog, and selecting a multi-gigabyte video should not mean uploading
 * it through the browser. This calls `GET /api/system/browse`, a read-only
 * directory listing restricted to directories and allow-listed media
 * extensions (see `backend/app/api/routers/system.py`), so the user can
 * navigate to a file and hand its *path* to the import endpoint.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { HardDrive, Folder, FileVideo, ChevronLeft, Loader2 } from "lucide-react";
import { systemApi } from "@/lib/api/resources";
import { Dialog, Button } from "@/components/ui";
import { formatBytes } from "@/lib/format";

export function FilePickerDialog({
  open,
  onClose,
  onSelect,
  title = "انتخاب فایل ویدئویی",
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  title?: string;
}) {
  const [path, setPath] = useState<string | undefined>(undefined);

  const { data, isLoading } = useQuery({
    queryKey: ["browse", path],
    queryFn: () => systemApi.browse(path),
    enabled: open,
  });

  return (
    <Dialog open={open} onClose={onClose} title={title} size="lg">
      <div className="space-y-3">
        {data?.current && (
          <div className="ltr flex items-center gap-1.5 overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
            {data.current}
          </div>
        )}

        <div className="max-h-96 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-800">
          {data?.parent && (
            <button
              onClick={() => setPath(data.parent!)}
              className="flex w-full items-center gap-2.5 border-b border-slate-100 px-3.5 py-2.5 text-sm text-slate-500 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
            >
              <ChevronLeft size={16} />
              پوشه بالاتر
            </button>
          )}

          {isLoading ? (
            <div className="flex items-center justify-center py-10 text-slate-400">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : !data || data.entries.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-400">پوشه‌ای یا فایلی پیدا نشد</p>
          ) : (
            data.entries.map((entry) => (
              <button
                key={entry.path}
                onClick={() => {
                  if (entry.type === "file") {
                    onSelect(entry.path);
                    onClose();
                  } else {
                    setPath(entry.path);
                  }
                }}
                className="flex w-full items-center justify-between gap-2.5 border-b border-slate-100 px-3.5 py-2.5 text-sm last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  {entry.type === "drive" ? (
                    <HardDrive size={16} className="shrink-0 text-slate-400" />
                  ) : entry.type === "directory" ? (
                    <Folder size={16} className="shrink-0 text-amber-400" />
                  ) : (
                    <FileVideo size={16} className="shrink-0 text-brand-500" />
                  )}
                  <span className="truncate text-slate-700 dark:text-slate-300">{entry.name}</span>
                </span>
                {entry.type === "file" && entry.size != null && (
                  <span className="num shrink-0 text-xs text-slate-400">{formatBytes(entry.size)}</span>
                )}
              </button>
            ))
          )}
        </div>

        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={onClose}>
            انصراف
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
