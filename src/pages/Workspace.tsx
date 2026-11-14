import { useRuns } from "@/hooks/useRuns";
import RunCard from "@/components/RunCard";
import { Plus, Rss } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { RunItem } from "@/hooks/useRuns";

export default function Workspace() {
  const navigate = useNavigate();
  const { runs, loading, error, refresh } = useRuns({ limit: 5 });

  async function remove(run: RunItem) {
    if (!window.confirm(`Delete “${run.topic}”?`)) return;
    try {
      await api(`/api/runs/${run.id}`, { method: "DELETE" });
      toast.success("Run deleted");
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete that run.");
    }
  }

  return (
    <div className="text-left">
      <header className="text-left">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          Active workspace
        </p>
        <h1 className="mt-2 text-[28px] font-bold tracking-tight text-fg sm:text-[34px]">
          Your research workspace.
        </h1>
        <p className="mt-2 max-w-[640px] text-[16px] text-muted sm:text-[17px] leading-relaxed">
          Start a new research run or pick up where you left off. Every run stores its outline,
          sources, and exports.
        </p>

        <button
          type="button"
          onClick={() => navigate("/runs/new")}
          className="mt-6 inline-flex h-[42px] items-center gap-2.5 rounded-lg bg-primary px-5 text-[14px] font-medium text-primary-fg shadow-sm transition hover:-translate-y-px"
        >
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary-fg/15 text-primary-fg">
            <Plus className="h-3.5 w-3.5 text-current" strokeWidth={2.5} aria-hidden="true" />
          </span>
          <span>New research run</span>
        </button>
      </header>

      <section className="mt-10 rounded-2xl border border-line bg-surface p-4 sm:p-6 text-left">
        <div className="flex items-center justify-between pb-4">
          <h2 className="text-base font-semibold text-fg">Recent runs</h2>
          <button
            type="button"
            onClick={() => navigate("/catalog")}
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted transition-colors hover:text-fg"
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
              <button type="button" onClick={refresh} className="ml-3 underline">
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
  );
}
