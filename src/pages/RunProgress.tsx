import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileDown,
  FileText,
  Loader2,
  Plus,
  RotateCcw,
  Square,
  Trash2,
  X,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { API_BASE, api, exportUrl } from "@/lib/api";

type StepState = "idle" | "running" | "done" | "failed";

interface StageEvent {
  type: string;
  node?: string;
  status?: string;
  message?: string;
  error?: string;
}

interface RunDetail {
  id: string;
  topic: string;
  title: string;
  status: "running" | "completed" | "failed";
  report_markdown: string;
  report_type: string;
  sources_count: number;
  word_count?: number;
  token_count?: number;
  cost_usd?: number;
  elapsed_seconds?: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

const STEPS = [
  { key: "research", label: "Research", hint: "Searching the web and gathering sources." },
  { key: "analysis", label: "Analysis", hint: "Reading the sources and extracting insights." },
  { key: "writing", label: "Writing", hint: "Drafting the structured report." },
];

function formatMSS(seconds?: number): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

export default function RunProgress() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [steps, setSteps] = useState<Record<string, { state: StepState; message?: string }>>({
    research: { state: "idle" },
    analysis: { state: "idle" },
    writing: { state: "idle" },
  });
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [copied, setCopied] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [stepsOpen, setStepsOpen] = useState(false);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const readerRef = useRef<AbortController | null>(null);

  const loadRun = useCallback(async () => {
    const data = await api<RunDetail>(`/api/runs/${id}`);
    setRun(data);
    if (data.status === "failed" && data.error_message) setFatalError(data.error_message);
    if (data.status === "completed") {
      setSteps({
        research: { state: "done", message: "Sources gathered" },
        analysis: { state: "done", message: "Insights extracted" },
        writing: { state: "done", message: "Report generated" },
      });
    }
    return data;
  }, [id]);

  useEffect(() => {
    void loadRun().catch((error) =>
      setFatalError(error instanceof Error ? error.message : "Could not load that run."),
    );
  }, [loadRun]);

  // Live timer while running
  useEffect(() => {
    if (!run || run.status !== "running") return;
    const interval = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(interval);
  }, [run]);

  // Stream progress while running
  useEffect(() => {
    if (!run || run.status !== "running") return;

    const controller = new AbortController();
    readerRef.current = controller;

    const connect = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/runs/${id}/stream`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (!response.body) throw new Error("No stream available.");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";

          for (const chunk of chunks) {
            const line = chunk.split("\n").find((item) => item.startsWith("data: "));
            if (!line) continue;
            const event: StageEvent = JSON.parse(line.slice(6));

            if (event.type === "stage" && event.node) {
              setSteps((current) => ({
                ...current,
                [event.node as string]: {
                  state:
                    event.status === "done"
                      ? "done"
                      : event.status === "error"
                        ? "failed"
                        : event.status === "running"
                          ? "running"
                          : "idle",
                  message: event.message,
                },
              }));
            } else if (event.type === "complete") {
              await loadRun();
            } else if (event.type === "error") {
              setFatalError(event.error ?? "An error occurred.");
              await loadRun();
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          await loadRun();
        }
      }
    };

    void connect();

    return () => {
      controller.abort();
    };
  }, [id, run?.status, loadRun]);

  // ESC key to close preview drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && previewOpen) {
        setPreviewOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewOpen]);

  async function cancel() {
    setCancelling(true);
    try {
      await api(`/api/runs/${id}/cancel`, { method: "POST" });
      readerRef.current?.abort();
      await loadRun();
      toast.message("Run cancelled.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not cancel.");
    } finally {
      setCancelling(false);
    }
  }

  async function retry() {
    setFatalError(null);
    try {
      await api(`/api/runs/${id}/retry`, { method: "POST" });
      setSteps({
        research: { state: "idle" },
        analysis: { state: "idle" },
        writing: { state: "idle" },
      });
      await loadRun();
      toast.success("Retrying run...");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not retry.");
    }
  }

  async function remove() {
    if (!window.confirm("Delete this run? This cannot be undone.")) return;
    try {
      await api(`/api/runs/${id}`, { method: "DELETE" });
      toast.success("Run deleted");
      navigate("/workspace");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete.");
    }
  }

  const copyReport = async () => {
    if (!run?.report_markdown) return;
    try {
      await navigator.clipboard.writeText(run.report_markdown);
      setCopied(true);
      toast.success("Report markdown copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy report");
    }
  };

  const isCompleted = run?.status === "completed";
  const isRunning = run?.status === "running";
  const isFailed = run?.status === "failed";

  const durationStr = formatMSS(run?.elapsed_seconds ?? seconds);
  const costStr = `$${Number(run?.cost_usd || 0).toFixed(4)}`;
  const tokensStr = run?.token_count ? run.token_count.toLocaleString() : "0";
  const reportTypeCapitalized = run?.report_type
    ? run.report_type.charAt(0).toUpperCase() + run.report_type.slice(1)
    : "Comprehensive";

  return (
    <div className="text-left">
      {/* Top Header */}
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-6">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-accent">
            <span>{reportTypeCapitalized}</span>
            <span>·</span>
            <span>
              {isRunning
                ? `Working… ${seconds}s elapsed`
                : isFailed
                  ? "Run failed"
                  : `Completed · ${run?.sources_count ?? 0} cited sources`}
            </span>
          </div>

          <h1 className="mt-2 text-2xl font-bold tracking-tight text-fg sm:text-3xl">
            {run?.title?.trim() || run?.topic || "Research run"}
          </h1>

          {/* Topic on its own line (no "About") */}
          {run && (
            <p className="mt-1 text-sm text-muted">
              {run.topic}
            </p>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {isRunning && (
            <button
              type="button"
              onClick={cancel}
              disabled={cancelling}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:bg-accent-soft disabled:opacity-60"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              Cancel
            </button>
          )}
          {isFailed && (
            <button
              type="button"
              onClick={retry}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-fg transition-opacity hover:opacity-90"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate("/runs/new")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:border-line-strong hover:bg-surface-hover"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            New run
          </button>
          <button
            type="button"
            onClick={remove}
            aria-label="Delete run"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted transition-colors hover:border-red-300 hover:text-red-600 dark:hover:border-red-800 dark:hover:text-red-400"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </header>

      {/* When running: show steps card */}
      {isRunning && (
        <section className="mt-8 rounded-2xl border border-line bg-surface p-6 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            Pipeline in progress
          </h2>
          <ol className="mt-4 flex flex-col gap-4">
            {STEPS.map((step, index) => {
              const state = steps[step.key];
              return (
                <li key={step.key} className="flex items-start gap-3">
                  <span
                    className={`mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
                      state?.state === "done"
                        ? "border-transparent bg-emerald-600 text-white"
                        : state?.state === "failed"
                          ? "border-transparent bg-red-600 text-white"
                          : state?.state === "running"
                            ? "border-accent text-accent"
                            : "border-line text-muted"
                    }`}
                  >
                    {state?.state === "done" ? (
                      <Check className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : state?.state === "running" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-fg">{step.label}</p>
                    <p className="text-xs text-muted">{state?.message ?? step.hint}</p>
                  </div>
                  <span className="text-xs capitalize text-muted">{state?.state}</span>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {/* When failed: show error */}
      {isFailed && (
        <div className="mt-8 rounded-2xl border border-red-200 bg-red-50 p-6 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <h2 className="text-sm font-bold">Research pipeline failed</h2>
          <p className="mt-1 text-xs">{fatalError || "An unexpected error occurred during execution."}</p>
          <button
            type="button"
            onClick={retry}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry now
          </button>
        </div>
      )}

      {/* When completed: Show PIPELINE bar & Centered REPORT READY block */}
      {isCompleted && (
        <div className="mt-8 space-y-6">
          {/* Compact PIPELINE bar */}
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface/80 px-4 py-3 text-xs shadow-sm">
            <div className="flex items-center gap-3">
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 ring-4 ring-emerald-500/20" />
              <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-600 dark:text-emerald-400">
                Completed
              </span>
              <span className="text-line-strong">|</span>
              <div className="flex items-center gap-3 text-muted">
                <span>{run?.sources_count ?? 0} sources</span>
                <span>·</span>
                <span>{tokensStr} tokens</span>
                <span>·</span>
                <span>{costStr}</span>
                <span>·</span>
                <span>{durationStr}</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setStepsOpen(!stepsOpen)}
                className="inline-flex items-center gap-1 rounded-lg border border-line bg-card px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:text-fg"
              >
                <span>Pipeline</span>
                {stepsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              </button>

              <button
                type="button"
                onClick={() => setPreviewOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-3 py-1 text-xs font-medium text-fg shadow-sm transition-colors hover:border-line-strong hover:bg-surface"
              >
                Preview
              </button>

              <Link
                to={`/reports/${id}`}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-white shadow-sm transition hover:opacity-90"
              >
                Report &rarr;
              </Link>
            </div>
          </div>

          {/* Collapsible Steps list if toggled */}
          {stepsOpen && (
            <div className="rounded-xl border border-line bg-surface/50 p-4 transition-all">
              <ol className="flex flex-col gap-3">
                {STEPS.map((step, idx) => (
                  <li key={step.key} className="flex items-center gap-2.5 text-xs">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-600 text-white">
                      <Check className="h-3 w-3" />
                    </span>
                    <span className="font-semibold text-fg">{idx + 1}. {step.label}</span>
                    <span className="text-muted">— {steps[step.key]?.message || "Done"}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Centered REPORT READY block */}
          <div className="mx-auto max-w-xl rounded-2xl border border-line bg-surface p-8 text-center shadow-lg shadow-black/5 dark:shadow-black/20 sm:p-10">
            <span className="text-xs font-bold uppercase tracking-[0.2em] text-accent">
              REPORT READY
            </span>
            <p className="mt-1 text-xs text-muted">
              Open the finished report or download it below.
            </p>

            {/* Circular check icon */}
            <div className="mx-auto mt-6 flex h-16 w-16 items-center justify-center rounded-full bg-accent-soft text-accent ring-8 ring-accent/10">
              <Check className="h-8 w-8 stroke-[2.5]" aria-hidden="true" />
            </div>

            <h2 className="mt-5 text-2xl font-bold tracking-tight text-fg">
              Report generated
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
              Your cited report is ready for review and export.
            </p>

            {/* Stats row: sources, tokens, cost, m:ss */}
            <div className="mt-6 grid grid-cols-4 divide-x divide-line rounded-xl border border-line bg-bg/60 p-3 text-center">
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Sources</p>
                <p className="mt-1 text-sm font-bold text-fg">{run?.sources_count ?? 0}</p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Tokens</p>
                <p className="mt-1 text-sm font-bold text-fg">{tokensStr}</p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Cost</p>
                <p className="mt-1 text-sm font-bold text-fg">{costStr}</p>
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-wider text-muted">Time</p>
                <p className="mt-1 text-sm font-bold text-fg">{durationStr}</p>
              </div>
            </div>

            {/* Action buttons: Open report & Download report */}
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <Link
                to={`/reports/${id}`}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-fg shadow-sm transition hover:opacity-90"
              >
                <span>Open report</span>
                <span aria-hidden="true">&rarr;</span>
              </Link>

              {/* Download report menu */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setDownloadMenuOpen(!downloadMenuOpen)}
                  className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-line bg-card px-5 text-sm font-semibold text-fg shadow-sm transition hover:border-line-strong hover:bg-surface"
                >
                  <Download className="h-4 w-4 text-accent" />
                  <span>Download report</span>
                  <ChevronDown className="h-3.5 w-3.5 text-muted" />
                </button>

                {downloadMenuOpen && (
                  <div className="absolute right-0 bottom-full mb-2 w-48 rounded-xl border border-line bg-card p-1.5 shadow-xl z-20">
                    <a
                      href={exportUrl(id, "pdf")}
                      onClick={() => setDownloadMenuOpen(false)}
                      className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-fg transition-colors hover:bg-surface"
                    >
                      <FileDown className="h-4 w-4 text-accent" />
                      <span>PDF Document (.pdf)</span>
                    </a>
                    <a
                      href={exportUrl(id, "docx")}
                      onClick={() => setDownloadMenuOpen(false)}
                      className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-fg transition-colors hover:bg-surface"
                    >
                      <FileText className="h-4 w-4 text-accent" />
                      <span>Word Document (.docx)</span>
                    </a>
                    <a
                      href={exportUrl(id, "md")}
                      onClick={() => setDownloadMenuOpen(false)}
                      className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-fg transition-colors hover:bg-surface"
                    >
                      <Download className="h-4 w-4 text-accent" />
                      <span>Markdown (.md)</span>
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Right-side Preview Drawer */}
      {previewOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
            onClick={() => setPreviewOpen(false)}
          />

          {/* Drawer Panel */}
          <div className="relative z-10 flex h-full w-full max-w-2xl flex-col border-l border-line bg-surface shadow-2xl">
            {/* Drawer Header */}
            <div className="flex items-center justify-between border-b border-line px-6 py-4">
              <div className="min-w-0 pr-4">
                <span className="text-[11px] font-bold uppercase tracking-wider text-accent">
                  PREVIEW
                </span>
                <h2 className="truncate text-base font-bold text-fg">
                  {run?.title?.trim() || run?.topic}
                </h2>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={copyReport}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-line bg-card px-2.5 text-xs font-medium text-muted hover:text-fg"
                >
                  {copied ? <Check className="h-3 w-3 text-accent" /> : <Copy className="h-3 w-3" />}
                  <span>{copied ? "Copied" : "Copy"}</span>
                </button>

                <a
                  href={exportUrl(id, "pdf")}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-line bg-card px-2.5 text-xs font-medium text-muted hover:text-fg"
                >
                  <FileDown className="h-3 w-3 text-accent" />
                  <span>PDF</span>
                </a>

                <a
                  href={exportUrl(id, "docx")}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-line bg-card px-2.5 text-xs font-medium text-muted hover:text-fg"
                >
                  <FileText className="h-3 w-3 text-accent" />
                  <span>Word</span>
                </a>

                <a
                  href={exportUrl(id, "md")}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-line bg-card px-2.5 text-xs font-medium text-muted hover:text-fg"
                >
                  <Download className="h-3 w-3 text-accent" />
                  <span>MD</span>
                </a>

                <button
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  aria-label="Close preview"
                  className="ml-2 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted hover:text-fg"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-6 sm:p-8">
              <div className="report-prose text-sm leading-relaxed text-fg">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {run?.report_markdown || "No report generated yet."}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
