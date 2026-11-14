import { useCallback, useEffect, useState } from "react";

export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface RunItem {
  id: string;
  topic: string;
  reportType: string;
  status: RunStatus;
  sourcesCount: number;
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
        const data = await fetch(`/api/runs?${params.toString()}`).then((r) =>
          r.ok ? r.json() : []
        );
        if (cancelled) return;
        setRuns(Array.isArray(data) ? data : []);
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
