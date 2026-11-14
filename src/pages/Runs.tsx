import { useRuns } from "@/hooks/useRuns";
import StatusBadge from "@/components/StatusBadge";
import { Trash2, Edit3, Search } from "lucide-react";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { RunItem } from "@/hooks/useRuns";
import RunCard from "@/components/RunCard";
import { useNavigate } from "react-router-dom";

export default function Runs() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const { runs, loading, error, refresh } = useRuns({ limit: 100, query });
  const navigate = useNavigate();

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

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

  async function rename(run: RunItem) {
    const next = window.prompt("Rename this run", run.topic);
    if (!next || next.trim() === run.topic) return;
    try {
      await api(`/api/runs/${run.id}`, {
        method: "PATCH",
        body: JSON.stringify({ topic: next.trim() }),
      });
      toast.success("Run renamed");
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not rename that run.");
    }
  }

  return (
    <div className="px-5 py-8 sm:px-10">
      <div className="mx-auto max-w-[1000px]">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[13px] font-medium uppercase tracking-[0.22em] text-muted">
              Recent runs
            </p>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-fg sm:text-[32px]">
              Every report you've made.
            </h1>
          </div>
          <label className="relative">
            <span className="sr-only">Search runs</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search runs"
              className="h-10 w-64 rounded-lg border border-line bg-surface pl-9 pr-3 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
        </header>

        <div className="flex flex-col gap-4">
          {loading ? (
            <div className="flex flex-col gap-4">
              {[0, 1, 2].map((index) => (
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
            <p className="rounded-xl border border-line bg-surface p-8 text-center text-sm text-muted">
              {query ? "No runs match that search." : "No runs yet. Start your first research run."}
            </p>
          ) : (
            runs.map((run) => (
              <RunCard key={run.id} run={run} onDelete={remove} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
