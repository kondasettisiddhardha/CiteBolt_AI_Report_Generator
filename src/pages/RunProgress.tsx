import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  Loader2,
  RotateCcw,
  Square,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { api, API_BASE, exportUrl } from "@/lib/api";

type StepState = "idle" | "running" | "done" | "failed";

interface StageEvent {
  type: "stage" | "report" | "error" | "end";
  node?: string;
  status?: string;
  message?: string;
  report?: string;
  sources?: unknown[];
}

interface SourceItem {
  number: string;
  title: string;
  url: string;
  domain: string;
  description: string;
}

const SOURCE_LINE =
  /^\s*(\d+)\.\s+\[([^\]]+)\]\((https?:\/\/[^)]+)\)(?:\s+[—-]\s+([^:]+))?(?::\s*(.*))?\s*$/;

/** Split the stored markdown into the summary, the body and structured sources. */
function splitReport(markdown: string) {
  const rawLines = markdown.split(/\r?\n/);
  const sourceHeading = rawLines.findIndex((line) =>
    /^##\s+(sources|references|bibliography)\s*$/i.test(line.trim()),
  );
  const bodyLines = sourceHeading >= 0 ? rawLines.slice(0, sourceHeading) : rawLines;
  const sourceLines = sourceHeading >= 0 ? rawLines.slice(sourceHeading + 1) : [];

  const sources: SourceItem[] = [];
  for (const line of sourceLines) {
    const match = line.match(SOURCE_LINE);
    if (!match) continue;
    sources.push({
      number: match[1],
      title: match[2],
      url: match[3],
      domain: (match[4] ?? "").trim(),
      description: (match[5] ?? "").trim(),
    });
  }

  const titleIndex = bodyLines.findIndex((line) => /^#\s+/.test(line.trim()));
  if (titleIndex >= 0) bodyLines.splice(titleIndex, 1);

  const summaryIndex = bodyLines.findIndex((line) =>
    /^##\s+executive summary\s*$/i.test(line.trim()),
  );
  let summary = "";
  if (summaryIndex >= 0) {
    let end = bodyLines.length;
    for (let index = summaryIndex + 1; index < bodyLines.length; index += 1) {
      if (/^#{1,3}\s+\S/.test(bodyLines[index].trim())) {
        end = index;
        break;
      }
    }
    summary = bodyLines.slice(summaryIndex + 1, end).join("\n").trim();
    bodyLines.splice(summaryIndex, end - summaryIndex);
  }

  return { summary, body: bodyLines.join("\n").trim(), sources };
}

const STEPS = [
  { key: "research", label: "Research", hint: "Searching the web and gathering sources." },
  { key: "analysis", label: "Analysis", hint: "Reading the sources and extracting insights." },
  { key: "writing", label: "Writing", hint: "Drafting the structured report." },
];

interface RunDetail {
  id: string;
  topic: string;
  title: string;
  status: "running" | "completed" | "failed";
  report_markdown: string;
  report_type: string;
  sources_count: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
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
  const [report, setReport] = useState("");
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [copied, setCopied] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const readerRef = useRef<AbortController | null>(null);

  const loadRun = useCallback(async () => {
    const data = await api<RunDetail>(`/api/runs/${id}`);
    setRun(data);
    if (data.report_markdown) setReport(data.report_markdown);
    if (data.status === "failed" && data.error_message) setFatalError(data.error_message);
    return data;
  }, [id]);

  useEffect(() => {
    void loadRun().catch((error) =>
      setFatalError(error instanceof Error ? error.message : "Could not load that run."),
    );
  }, [loadRun]);

  // Stream progress while the run is live.
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
            }

            if (event.type === "report" && event.report) {
              setReport(event.report);
              setFatalError(null);
            }

            if (event.type === "error") {
              setFatalError(event.message ?? "The run failed.");
            }

            if (event.type === "end") {
              await loadRun().catch(() => undefined);
            }
          }
        }
        await loadRun().catch(() => undefined);
      } catch (error) {
        if (!controller.signal.aborted) {
          setFatalError(error instanceof Error ? error.message : "Lost connection to the run.");
        }
      }
    };

    void connect();
    return () => controller.abort();
  }, [run, id, loadRun]);

  useEffect(() => {
    if (run?.status !== "running") return;
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [run?.status]);

  useEffect(() => {
    if (!run?.created_at) return;
    setSeconds(Math.max(0, Math.round((Date.now() - new Date(run.created_at).getTime()) / 1000)));
  }, [run?.created_at]);

  async function cancel() {
    setCancelling(true);
    try {
      await api(`/api/runs/${id}/cancel`, { method: "POST" });
      toast.success("Run cancelled");
      await loadRun();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not cancel the run.");
    } finally {
      setCancelling(false);
    }
  }

  async function retry() {
    try {
      const data = await api<{ run_id: string }>(`/api/runs/${id}/retry`, { method: "POST" });
      toast.success("Retrying with a fresh run");
      navigate(`/runs/${data.run_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not retry that run.");
    }
  }

  async function copyReport() {
    await navigator.clipboard.writeText(report);
    setCopied(true);
    toast.success("Report copied");
    window.setTimeout(() => setCopied(false), 2000);
  }

  async function remove() {
    if (!window.confirm("Delete this run?")) return;
    try {
      await api(`/api/runs/${id}`, { method: "DELETE" });
      toast.success("Run deleted");
      navigate("/runs");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete the run.");
    }
  }

  const finished = run?.status === "completed" || (!!report && run?.status !== "running");
  const parsed = useMemo(() => (report ? splitReport(report) : null), [report]);
  const reportTitle = run?.title?.trim() || run?.topic || "Research report";
  const createdLabel = run?.created_at
    ? new Date(run.created_at).toLocaleDateString(undefined, {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : "";
  const typeLabel = run?.report_type
    ? run.report_type.replace(/([a-z])([A-Z])/g, "$1 $2")
    : "Research report";

  return (
    <div className="px-5 py-8 sm:px-10">
      <div className="mx-auto max-w-[900px]">
        <button
          type="button"
          onClick={() => navigate("/workspace")}
          className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Workspace
        </button>

        <header className="mt-5 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">
              {run ? run.title?.trim() || run.topic : "Loading run…"}
            </h1>
            <p className="mt-1 text-sm text-muted">
              {run?.status === "running"
                ? `Working… ${seconds}s elapsed`
                : run?.status === "failed"
                  ? "This run failed"
                  : run?.status === "completed"
                    ? `Completed · ${run.sources_count} cited sources`
                    : "Loading…"}
              {run && run.title !== run.topic ? ` · ${run.topic}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {run?.status === "running" && (
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
            {run?.status === "failed" && (
              <button
                type="button"
                onClick={retry}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-fg"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={remove}
              aria-label="Delete run"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted transition-colors hover:text-red-600 dark:hover:text-red-400"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </header>

        <section className="mt-6 rounded-2xl border border-line bg-surface p-5">
          <ol className="flex flex-col gap-4">
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
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg">{step.label}</p>
                    <p className="text-xs text-muted">
                      {state?.message ?? step.hint}
                    </p>
                  </div>
                  <span className="ml-auto text-xs capitalize text-muted">{state?.state}</span>
                </li>
              );
            })}
          </ol>

          {fatalError && run?.status === "failed" && (
            <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {fatalError}
            </p>
          )}
        </section>

        {report && (
          <section className="mt-6 rounded-2xl border border-line bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
              <h2 className="text-sm font-semibold text-fg">Report</h2>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={copyReport}
                  className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-fg"
                >
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                  Copy
                </button>
                {(["md", "pdf", "docx"] as const).map((format) => (
                  <a
                    key={format}
                    href={exportUrl(id, format)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-fg"
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    {format.toUpperCase()}
                  </a>
                ))}
                {finished && (
                  <button
                    type="button"
                    onClick={() => navigate("/runs/new")}
                    className="rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-fg"
                  >
                    New run
                  </button>
                )}
              </div>
            </div>

            <div className="p-5 sm:p-8">
              <header className="border-b-[1.5px] border-accent pb-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  Dossier Research Report
                </p>
                <h2 className="mt-2 text-2xl font-bold leading-tight tracking-tight text-fg sm:text-[26px]">
                  {reportTitle}
                </h2>
                <p className="mt-2 text-xs text-muted">
                  {[createdLabel, typeLabel, `${run?.sources_count ?? 0} sources`, run?.topic]
                    .filter(Boolean)
                    .join("  ·  ")}
                </p>
              </header>

              {parsed?.summary && (
                <section className="mt-6 rounded-lg border-l-[3px] border-accent bg-accent-soft px-4 py-3.5">
                  <h3 className="text-base font-semibold text-fg">Executive Summary</h3>
                  <div className="report-body mt-1.5 text-[15px] leading-[1.65] text-fg">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{parsed.summary}</ReactMarkdown>
                  </div>
                </section>
              )}

              <div className="report-body mt-6 text-[15px] leading-[1.65] text-fg">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {parsed?.body || report}
                </ReactMarkdown>
              </div>

              {!!parsed?.sources.length && (
                <section className="mt-10 border-t border-line pt-6">
                  <h2 className="text-xl font-semibold tracking-tight text-fg">Sources</h2>
                  <ol className="mt-4 space-y-3 text-[15px] leading-[1.6]">
                    {parsed.sources.map((source) => (
                      <li key={source.number} className="text-fg">
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-fg underline-offset-2 hover:text-accent hover:underline"
                        >
                          {source.title}
                        </a>
                        {source.domain && (
                          <span className="ml-1.5 text-sm text-muted">— {source.domain}</span>
                        )}
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-0.5 block break-all text-xs text-muted hover:text-accent"
                        >
                          {source.url}
                        </a>
                        {source.description && (
                          <span className="mt-0.5 block text-sm text-muted">
                            {source.description}
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                </section>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
