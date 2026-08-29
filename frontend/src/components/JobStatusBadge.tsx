import { Badge } from "@/components/ui";
import type { JobStatus } from "@/lib/api/types";

const config: Record<JobStatus, { label: string; tone: "neutral" | "info" | "success" | "danger" | "warning" }> = {
  queued: { label: "در صف", tone: "neutral" },
  running: { label: "در حال اجرا", tone: "info" },
  completed: { label: "تکمیل شد", tone: "success" },
  failed: { label: "ناموفق", tone: "danger" },
  cancelled: { label: "لغو شد", tone: "warning" },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const { label, tone } = config[status];
  return <Badge tone={tone} dot>{label}</Badge>;
}
