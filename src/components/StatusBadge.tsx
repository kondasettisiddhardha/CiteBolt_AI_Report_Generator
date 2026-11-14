import type { RunStatus } from "@/hooks/useRuns";
import { CheckCircle, Circle, Loader2, XCircle } from "lucide-react";

const statusColors: Record<RunStatus, string> = {
  queued: "bg-amber-500",
  running: "bg-amber-500 animate-pulse",
  completed: "bg-emerald-600",
  failed: "bg-red-600",
};

const labelColors: Record<RunStatus, string> = {
  queued: "bg-amber-50 text-amber-700",
  running: "bg-amber-50 text-amber-700",
  completed: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-700",
};

export default function StatusBadge({ status }: { status: RunStatus }) {
  const Icon = status === "running" ? Loader2 : status === "completed" ? CheckCircle : status === "failed" ? XCircle : Circle;
  const color = statusColors[status];
  const label = labelColors[status];

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium ${label}`}
      role="status"
      aria-label={`Status: ${status}`}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      <span className="capitalize">{status}</span>
    </span>
  );
}
