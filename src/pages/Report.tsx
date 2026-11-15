import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { format } from "date-fns";
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  FileDown,
  FileText,
  List,
  Loader2,
  Share2,
} from "lucide-react";
import { toast } from "sonner";
import { api, exportUrl } from "@/lib/api";

interface SourceItem {
  id?: number;
  number?: number;
  n?: number;
  title: string;
  url: string;
  domain?: string;
  description?: string;
  snippet?: string;
  content?: string;
}

interface RunDetail {
  id: string;
  topic: string;
  title?: string;
  report_type: string;
  status: string;
  report_markdown: string;
  sources: SourceItem[];
  sources_count: number;
  word_count?: number;
  token_count: number;
  cost_usd: number;
  elapsed_seconds: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
}

interface HeadingItem {
  id: string;
  text: string;
  level: 2 | 3;
  displayNumber: string;
}

function countWords(markdown: string): number {
  if (!markdown) return 0;
  const clean = markdown
    .replace(/^#+.*$/gm, "")
    .replace(/\[\d+\]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#]/g, " ")
    .trim();
  const words = clean.match(/[\w'-]+/g);
  return words ? words.length : 0;
}

function formatMSS(seconds?: number): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "Just now";
  try {
    const d = new Date(dateStr);
    return format(d, "MMM d, yyyy · h:mm a");
  } catch {
    return dateStr;
  }
}

function cleanHeadingText(raw: string): string {
  return raw.replace(/^(?:\d+(?:\.\d+)*[\.\-\)]\s*)+/, "").trim();
}

function extractHeadings(markdown: string): HeadingItem[] {
  const lines = markdown.split(/\r?\n/);
  const items: HeadingItem[] = [];
  const seenSlugs = new Set<string>();
  let h2Count = 0;
  let h3Count = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    const h2Match = trimmed.match(/^##\s+(.+)$/);
    const h3Match = trimmed.match(/^###\s+(.+)$/);

    if (h2Match) {
      const rawText = h2Match[1].replace(/\{#.*?\}/, "").replace(/\*\*/g, "").trim();
      const text = cleanHeadingText(rawText);
      const lower = text.toLowerCase();
      if (
        lower === "references" ||
        lower === "sources" ||
        lower.startsWith("sources:") ||
        lower === "table of contents"
      ) {
        continue;
      }
      h2Count++;
      h3Count = 0;
      const slug = text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/(^-|-$)/g, "");
      if (!seenSlugs.has(slug)) {
        seenSlugs.add(slug);
        items.push({
          id: slug,
          text,
          level: 2,
          displayNumber: `${h2Count}.`,
        });
      }
    } else if (h3Match) {
      const rawText = h3Match[1].replace(/\{#.*?\}/, "").replace(/\*\*/g, "").trim();
      const text = cleanHeadingText(rawText);
      const lower = text.toLowerCase();
      if (lower === "references" || lower === "sources") continue;
      h3Count++;
      const slug = text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/(^-|-$)/g, "");
      if (!seenSlugs.has(slug)) {
        seenSlugs.add(slug);
        items.push({
          id: slug,
          text,
          level: 3,
          displayNumber: `${h2Count}.${h3Count}`,
        });
      }
    }
  }
  return items;
}

export default function Report() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copiedBody, setCopiedBody] = useState(false);
  const [activeHeading, setActiveHeading] = useState<string>("");

  useEffect(() => {
    if (!id) return;
    let mounted = true;

    async function load() {
      try {
        setLoading(true);
        const data = await api<RunDetail>(`/api/runs/${id}`);
        if (!mounted) return;
        setRun(data);
        setError(null);
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to load report.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [id]);

  const headings = useMemo(() => {
    return run?.report_markdown ? extractHeadings(run.report_markdown) : [];
  }, [run?.report_markdown]);

  // Observer for active heading scroll-spy
  useEffect(() => {
    if (!headings.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeading(entry.target.id);
            break;
          }
        }
      },
      { rootMargin: "0px 0px -70% 0px" },
    );

    for (const h of headings) {
      const el = document.getElementById(h.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [headings]);

  const sourcesMap = useMemo(() => {
    const map = new Map<number, SourceItem>();
    if (!run?.sources) return map;
    run.sources.forEach((s, idx) => {
      const num = s.number ?? s.id ?? s.n ?? idx + 1;
      map.set(num, s);
    });
    return map;
  }, [run?.sources]);

  // Transform citations [n] and 【n】 into linkable targets
  const transformedMarkdown = useMemo(() => {
    if (!run?.report_markdown) return "";
    return run.report_markdown.replace(/[\[【](\d{1,3})[\]】]/g, "[$1](#source-$1)");
  }, [run?.report_markdown]);

  const words = useMemo(() => {
    if (run?.word_count && run.word_count > 0) return run.word_count;
    return countWords(run?.report_markdown ?? "");
  }, [run?.word_count, run?.report_markdown]);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      toast.success("Report link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy link");
    }
  };

  const copyMarkdown = async () => {
    if (!run?.report_markdown) return;
    try {
      await navigator.clipboard.writeText(run.report_markdown);
      setCopiedBody(true);
      toast.success("Markdown copied to clipboard");
      setTimeout(() => setCopiedBody(false), 2000);
    } catch {
      toast.error("Could not copy markdown");
    }
  };

  const scrollToHeading = (headingId: string) => {
    const el = document.getElementById(headingId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
      setActiveHeading(headingId);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-accent" />
        <p className="text-sm text-muted">Loading research report...</p>
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <p className="text-sm text-red-500">{error ?? "Report not found."}</p>
        <button
          onClick={() => navigate("/workspace")}
          className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to workspace
        </button>
      </div>
    );
  }

  const title = run.title?.trim() || run.topic;
  const timeFormatted =
    run.elapsed_seconds && run.elapsed_seconds > 0 ? formatMSS(run.elapsed_seconds) : "N/A";
  const costFormatted =
    run.cost_usd && run.cost_usd > 0 ? `$${Number(run.cost_usd).toFixed(4)}` : "N/A";
  const tokenFormatted =
    run.token_count && run.token_count > 0 ? run.token_count.toLocaleString() : "N/A";

  return (
    <div className="text-left">
      {/* Two-column layout: Left Article (max 720px), Right Sticky Summary Card */}
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
        {/* Left Column: Article */}
        <article className="min-w-0 max-w-[720px]">
          {/* Eyebrow */}
          <div>
            <span className="text-xs font-bold uppercase tracking-[0.2em] text-accent">
              REPORT
            </span>
          </div>

          {/* Title */}
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-fg sm:text-[32px] sm:leading-[1.25]">
            {title}
          </h1>

          {/* Subtitle */}
          <p className="mt-2 text-sm text-muted">
            Generated in {timeFormatted !== "N/A" ? timeFormatted : "under a minute"} from {run.sources_count} cited sources · {words.toLocaleString()} words.
          </p>

          {/* Available exports bar */}
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface/60 p-2 text-xs">
            <span className="px-2 font-medium text-muted">Available exports:</span>
            <a
              href={exportUrl(run.id, "pdf")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-2.5 py-1 font-medium text-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              <FileDown className="h-3.5 w-3.5 text-accent" />
              PDF
            </a>
            <a
              href={exportUrl(run.id, "docx")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-2.5 py-1 font-medium text-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              <FileText className="h-3.5 w-3.5 text-accent" />
              Word
            </a>
            <a
              href={exportUrl(run.id, "md")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-2.5 py-1 font-medium text-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              <Download className="h-3.5 w-3.5 text-accent" />
              Markdown
            </a>
            <button
              type="button"
              onClick={copyMarkdown}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-2.5 py-1 font-medium text-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              {copiedBody ? <Check className="h-3.5 w-3.5 text-accent" /> : <Copy className="h-3.5 w-3.5 text-accent" />}
              {copiedBody ? "Copied" : "Copy"}
            </button>
          </div>

          {/* CONTENTS card: ONE column in document order built from H2 headings with H3 nested and numbered */}
          {headings.length > 0 && (
            <div className="mt-6 rounded-xl border border-line bg-surface p-5 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted">
                <List className="h-3.5 w-3.5 text-accent" />
                <span>CONTENTS</span>
              </div>
              <nav aria-label="Table of contents" className="flex flex-col space-y-1.5">
                {headings.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    onClick={() => scrollToHeading(h.id)}
                    title={h.text}
                    className={`flex items-baseline gap-2 truncate text-left text-xs transition-colors hover:text-fg ${
                      activeHeading === h.id ? "font-bold text-accent" : "text-muted"
                    } ${h.level === 3 ? "pl-4 text-[11px]" : "font-medium"}`}
                  >
                    <span className="shrink-0 text-muted/70">{h.displayNumber}</span>
                    <span className="truncate">{h.text}</span>
                  </button>
                ))}
              </nav>
            </div>
          )}

          {/* Article Markdown Content */}
          <div className="report-prose mt-8 text-[16px] sm:text-[17px] leading-[1.7] text-fg">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => (
                  <h2 className="mt-8 mb-4 text-2xl font-bold tracking-tight text-fg border-b border-line pb-2">
                    {children}
                  </h2>
                ),
                h2: ({ children }) => {
                  const rawText = String(children).replace(/\*\*/g, "").trim();
                  const text = cleanHeadingText(rawText);
                  const slug = text
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/(^-|-$)/g, "");
                  return (
                    <h2
                      id={slug}
                      className="mt-8 mb-3 text-xl font-bold tracking-tight text-fg scroll-mt-20 border-b border-line pb-2"
                    >
                      {text}
                    </h2>
                  );
                },
                h3: ({ children }) => {
                  const rawText = String(children).replace(/\*\*/g, "").trim();
                  const text = cleanHeadingText(rawText);
                  const slug = text
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/(^-|-$)/g, "");
                  return (
                    <h3
                      id={slug}
                      className="mt-6 mb-2 text-base font-semibold text-fg scroll-mt-20"
                    >
                      {text}
                    </h3>
                  );
                },
                p: ({ children }) => <p className="mb-4">{children}</p>,
                ul: ({ children }) => <ul className="mb-4 list-disc pl-5 space-y-1.5">{children}</ul>,
                ol: ({ children }) => <ol className="mb-4 list-decimal pl-5 space-y-1.5">{children}</ol>,
                blockquote: ({ children }) => (
                  <blockquote className="my-4 border-l-4 border-accent bg-accent-soft/40 p-4 rounded-r-lg text-fg italic">
                    {children}
                  </blockquote>
                ),
                table: ({ children }) => (
                  <div className="my-6 w-full overflow-x-auto rounded-lg border border-line">
                    <table className="w-full text-left text-sm border-collapse">{children}</table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="bg-surface border-b border-line">{children}</thead>
                ),
                th: ({ children }) => (
                  <th className="px-3.5 py-2.5 font-semibold text-fg border-r border-line last:border-r-0">
                    {children}
                  </th>
                ),
                tr: ({ children }) => (
                  <tr className="border-b border-line last:border-b-0 even:bg-surface/30 hover:bg-surface/60 transition-colors">
                    {children}
                  </tr>
                ),
                td: ({ children }) => (
                  <td className="px-3.5 py-2.5 text-fg border-r border-line last:border-r-0">
                    {children}
                  </td>
                ),
                a: ({ href, children }) => {
                  if (href?.startsWith("#source-")) {
                    const numStr = href.replace("#source-", "");
                    const num = parseInt(numStr, 10);
                    const source = sourcesMap.get(num);
                    const tooltip = source
                      ? `${source.title}${source.domain ? ` — ${source.domain}` : ""}`
                      : `Source ${numStr}`;
                    return (
                      <a
                        href={href}
                        title={tooltip}
                        onClick={(e) => {
                          e.preventDefault();
                          const el = document.getElementById(`source-${numStr}`);
                          if (el) el.scrollIntoView({ behavior: "smooth" });
                        }}
                        className="inline-flex items-center justify-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent transition-colors hover:bg-accent hover:text-white mx-0.5 align-baseline focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        [{children}]
                      </a>
                    );
                  }
                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent underline underline-offset-2 hover:opacity-80"
                    >
                      {children}
                    </a>
                  );
                },
              }}
            >
              {transformedMarkdown}
            </ReactMarkdown>
          </div>

          {/* References Section at the end: numbered 1..N with no gaps, linked title, domain, URL */}
          {run.sources && run.sources.length > 0 && (
            <section id="references" className="mt-12 border-t border-line pt-8">
              <h2 className="text-xl font-bold tracking-tight text-fg">References</h2>
              <ol className="mt-4 space-y-4">
                {run.sources.map((source, index) => {
                  const num = index + 1;
                  return (
                    <li
                      key={num}
                      id={`source-${num}`}
                      className="scroll-mt-24 rounded-lg p-2.5 transition-colors hover:bg-surface/50"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="font-bold text-accent">[{num}]</span>
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-fg hover:text-accent hover:underline"
                        >
                          {source.title}
                        </a>
                        {source.domain && (
                          <span className="text-xs text-muted">— {source.domain}</span>
                        )}
                      </div>
                      {source.url && (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 block break-all text-xs text-muted hover:text-accent hover:underline"
                        >
                          {source.url}
                        </a>
                      )}
                      {(source.description || source.snippet || source.content) && (
                        <p className="mt-1 text-sm text-muted">
                          {source.description || source.snippet || source.content}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          )}
        </article>

        {/* Right Column: Sticky "Run summary" card */}
        <aside className="sticky top-6 rounded-2xl border border-line bg-card p-5 shadow-sm">
          <h2 className="text-sm font-bold tracking-tight text-fg">Run summary</h2>

          <div className="mt-4 divide-y divide-line text-xs">
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Updated</span>
              <span className="font-medium text-fg">
                {formatDate(run.completed_at || run.created_at)}
              </span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Sources</span>
              <span className="font-medium text-fg">{run.sources_count}</span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Tokens</span>
              <span className="font-medium text-fg">
                {tokenFormatted}
              </span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Cost</span>
              <span className="font-medium text-fg">{costFormatted}</span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Time</span>
              <span className="font-medium text-fg">{timeFormatted}</span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-muted">Words</span>
              <span className="font-medium text-fg">{words.toLocaleString()}</span>
            </div>
          </div>

          {/* Export buttons */}
          <div className="mt-6 flex flex-col gap-2">
            <a
              href={exportUrl(run.id, "pdf")}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-line bg-surface py-2 text-xs font-semibold text-fg transition-colors hover:bg-surface-hover hover:border-line-strong"
            >
              <FileDown className="h-4 w-4 text-accent" />
              Download PDF
            </a>
            <a
              href={exportUrl(run.id, "docx")}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-line bg-surface py-2 text-xs font-semibold text-fg transition-colors hover:bg-surface-hover hover:border-line-strong"
            >
              <FileText className="h-4 w-4 text-accent" />
              Download Word (.docx)
            </a>
            <a
              href={exportUrl(run.id, "md")}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-line bg-surface py-2 text-xs font-semibold text-fg transition-colors hover:bg-surface-hover hover:border-line-strong"
            >
              <Download className="h-4 w-4 text-accent" />
              Download Markdown
            </a>
            <button
              onClick={copyLink}
              type="button"
              className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-2 text-xs font-semibold text-primary-fg shadow-sm transition-opacity hover:opacity-90"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              <span>{copied ? "Link copied!" : "Copy link"}</span>
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
