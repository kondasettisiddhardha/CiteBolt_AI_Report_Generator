import type { RunStatus } from "@/hooks/useRuns";
import { AlertTriangle, CheckCircle, Circle, Loader2, XCircle } from "lucide-react";

const statusColors: Record<RunStatus, string> = {
  queued: "bg-amber-500",
  running: "bg-amber-500 animate-pulse",
  completed: "bg-emerald-600",
  completed_with_warnings: "bg-amber-500",
  failed: "bg-red-600",
  interrupted: "bg-zinc-500",
  cancelled: "bg-zinc-500",
};

const labelColors: Record<RunStatus, string> = {
  queued: "bg-amber-50 text-amber-700",
  running: "bg-amber-50 text-amber-700",
  completed: "bg-emerald-50 text-emerald-700",
  completed_with_warnings: "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 border border-amber-300 dark:border-amber-800",
  failed: "bg-red-50 text-red-700",
  interrupted: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  cancelled: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

export default function StatusBadge({ status }: { status: RunStatus }) {
  const Icon =
    status === "running"
      ? Loader2
      : status === "completed"
        ? CheckCircle
        : status === "completed_with_warnings"
          ? AlertTriangle
          : status === "failed"
            ? XCircle
            : Circle;
  const color = statusColors[status] || "bg-zinc-500";
  const label = labelColors[status] || "bg-zinc-100 text-zinc-700";

  const displayText =
    status === "completed_with_warnings"
      ? "Completed with warnings"
      : status;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium ${label}`}
      role="status"
      aria-label={`Status: ${displayText}`}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      <span className="capitalize">{displayText}</span>
    </span>
  );
}
