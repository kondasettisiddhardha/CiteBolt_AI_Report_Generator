import { useState } from "react";
import { useRuns } from "@/hooks/useRuns";
import RunCard from "@/components/RunCard";
import { Plus, Rss } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { RunItem } from "@/hooks/useRuns";

export default function Workspace() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const data = (await api<RunItem[]>(`/api/runs?limit=20`)) as RunItem[];
      setRuns(data.slice(0, 5));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load runs.");
    } finally {
      setLoading(false);
    }
  }

  async function remove(run: RunItem) {
    if (!window.confirm(`Delete “${run.topic}”?`)) return;
    try {
      await api(`/api/runs/${run.id}`, { method: "DELETE" });
      toast.success("Run deleted");
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete that run.");
    }
  }

  return (
    <div className="px-5 py-12 sm:px-10 sm:py-14">
      <div className="mx-auto max-w-[1120px]">
        <header className="text-center">
          <p className="text-[13px] font-medium uppercase tracking-[0.22em] text-muted">
            Active workspace
          </p>
          <h1 className="mt-4 text-[34px] font-bold leading-tight tracking-tight text-fg sm:text-[48px]">
            Your research workspace.
          </h1>
          <p className="mx-auto mt-4 max-w-[620px] text-base text-muted sm:text-[18px]">
            Start a new research run or pick up where you left off. Every run stores its outline,
            sources, and exports.
          </p>

          <button
            type="button"
            onClick={() => navigate("/runs/new")}
            className="mt-8 inline-flex items-center gap-2.5 rounded-lg bg-primary px-5 py-3 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px dark:shadow-[0_0_0_4px_rgba(255,255,255,0.06),0_10px_30px_-12px_rgba(255,255,255,0.55)]"
          >
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary-fg/10 dark:bg-neutral-950">
              <Plus className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden="true" />
            </span>
            New research run
          </button>
        </header>

        <section className="mt-12 rounded-2xl border border-line bg-surface p-4 sm:p-6">
          <div className="flex items-center justify-between pb-4">
            <h2 className="text-base font-semibold text-fg">Recent runs</h2>
            <button
              type="button"
              onClick={() => navigate("/catalog")}
              className="inline-flex items-center gap-1.5 rounded-md text-xs text-muted transition-colors hover:text-fg"
            >
              <Rss className="h-3.5 w-3.5" aria-hidden="true" />
              View catalog
            </button>
          </div>
          <div className="border-t border-line" />

          <div className="mt-4 flex flex-col gap-4">
            {loading ? (
              <div className="flex flex-col gap-4">
                {[0, 1].map((index) => (
                  <div key={index} className="h-[132px] animate-pulse rounded-xl border border-line bg-card" />
                ))}
              </div>
            ) : error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                {error}
                <button type="button" onClick={load} className="ml-3 underline">
                  retry
                </button>
              </div>
            ) : runs.length === 0 ? (
              <p className="rounded-xl border border-line bg-card p-8 text-center text-sm text-muted">
                No runs yet. Start your first research run.
              </p>
            ) : (
              runs.map((run) => (
                <RunCard key={run.id} run={run} onDelete={remove} />
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
