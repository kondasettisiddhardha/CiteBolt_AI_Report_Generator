import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import { Clock, FileText, ExternalLink, Rss, Trash2, Zap } from "lucide-react";
import type { RunItem } from "@/hooks/useRuns";
import { exportUrl } from "@/lib/api";
import StatusBadge from "./StatusBadge";

function formatSafeDistance(dateVal?: string | null): string {
  if (!dateVal) return "recently";
  try {
    const d = new Date(dateVal);
    if (isNaN(d.getTime())) return "recently";
    return formatDistanceToNow(d, { addSuffix: true });
  } catch {
    return "recently";
  }
}

export default function RunCard({ run, onDelete }: { run: RunItem; onDelete?: (run: RunItem) => void }) {
  const anyRun = run as unknown as Record<string, unknown>;
  const createdAt = run.createdAt || (anyRun.created_at as string) || new Date().toISOString();
  const completedAt = run.completedAt || (anyRun.completed_at as string) || null;
  const finishedAt = completedAt || createdAt;
  const sourcesCount = run.sourcesCount ?? (anyRun.sources_count as number) ?? 0;

  return (
    <article className="flex flex-col gap-4 rounded-xl border border-line bg-card p-4 transition-colors hover:border-line-strong sm:flex-row sm:items-start sm:justify-between sm:p-5">
      <div className="order-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={run.status} />
          <span className="text-sm text-muted" aria-hidden="true">
            ·
          </span>
          <time className="text-sm text-muted" dateTime={finishedAt}>
            {formatSafeDistance(finishedAt)}
          </time>
        </div>

        <h3 className="mt-2 truncate text-xl font-semibold tracking-tight text-fg">{run.topic}</h3>
        <p className="mt-1 truncate text-sm text-muted">{sourcesCount} cited sources</p>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            {formatSafeDistance(createdAt)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Rss className="h-3.5 w-3.5" aria-hidden="true" />
            {sourcesCount} sources
          </span>
          {Boolean(run.tokenCount && run.tokenCount > 0) && (
            <span className="inline-flex items-center gap-1.5">
              <Zap className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
              {run.tokenCount?.toLocaleString()} tokens
            </span>
          )}
        </div>
      </div>

      <div className="order-2 flex items-center gap-2 sm:shrink-0">
        {(run.status === "completed" || run.status === "completed_with_warnings") && (
          <a
            href={exportUrl(run.id, "md")}
            className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-fg"
          >
            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
            MD
          </a>
        )}
        <Link
          to={(run.status === "completed" || run.status === "completed_with_warnings") ? `/reports/${run.id}` : `/runs/${run.id}`}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-fg"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          Open
        </Link>
        {onDelete && (
          <button
            type="button"
            onClick={() => onDelete(run)}
            aria-label={`Delete ${run.topic}`}
            className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-line text-muted transition-colors hover:border-red-300 hover:text-red-600 dark:hover:text-red-400"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      </div>
    </article>
  );
}
