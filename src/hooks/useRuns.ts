import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "interrupted"
  | "cancelled";

export interface RunItem {
  id: string;
  topic: string;
  title?: string;
  reportType: string;
  status: RunStatus;
  sourcesCount: number;
  wordCount?: number;
  tokenCount?: number;
  costUsd?: number;
  elapsedSeconds?: number;
  createdAt: string;
  completedAt: string | null;
  error_message: string | null;
}

export interface RunListOptions {
  limit?: number;
  query?: string;
  enabled?: boolean;
  poll?: boolean;
}

export function useRuns(options?: RunListOptions) {
  const limit = options?.limit ?? 20;
  const query = options?.query ?? "";
  const enabled = options?.enabled ?? true;

  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => setRuns((current) => current.map((r) => ({ ...r }))), []);

  useEffect(() => {
    if (!enabled) {
      setRuns([]);
      setError(null);
      setLoading(false);
      return () => undefined;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const params = new URLSearchParams({ limit: String(limit), query });
        const data = await api<unknown[]>(`/api/runs?${params.toString()}`).catch(() => []);
        if (cancelled) return;
        const rawList = Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
        const normalized: RunItem[] = rawList.map((item) => ({
          id: String(item.id ?? ""),
          topic: String(item.topic ?? ""),
          reportType: String(item.reportType ?? item.report_type ?? "auto"),
          status: (item.status as RunStatus) ?? "queued",
          sourcesCount: Number(item.sourcesCount ?? item.sources_count ?? 0),
          wordCount: Number(item.wordCount ?? item.word_count ?? 0),
          tokenCount: Number(item.tokenCount ?? item.token_count ?? 0),
          costUsd: Number(item.costUsd ?? item.cost_usd ?? 0),
          elapsedSeconds: Number(item.elapsedSeconds ?? item.elapsed_seconds ?? 0),
          createdAt: String(item.createdAt ?? item.created_at ?? new Date().toISOString()),
          completedAt: item.completedAt ? String(item.completedAt) : item.completed_at ? String(item.completed_at) : null,
          error_message: item.error_message ? String(item.error_message) : null,
        }));
        setRuns(normalized);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setRuns([]);
        setError(err instanceof Error ? err.message : "Could not load runs.");
      } finally {
        if (cancelled) return;
        setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [limit, query, enabled, refresh]);

  return { runs, loading, error, refresh };
}
