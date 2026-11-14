import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, FileText, Loader2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { extractPdfText } from "@/lib/pdf";
import { loadDraft, saveDraft } from "@/lib/session";

export const MAX_CONTEXT = 40000;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

const TEXT_TYPES = [".txt", ".md", ".markdown", ".csv", ".json", ".log"];

export const REPORT_TYPES = [
  {
    value: "auto",
    label: "Auto",
    description: "The planner picks the shape and length that suits the topic.",
  },
  { value: "briefing", label: "Briefing", description: "5-6 tight sections. Fastest to read." },
  {
    value: "deepdive",
    label: "Deep dive",
    description: "9-11 sections with foundations, theory, and counterarguments.",
  },
  {
    value: "architectureblueprint",
    label: "Architecture blueprint",
    description: "Requirements, components, data flow, trade-offs, and a delivery plan.",
  },
] as const;

export type ReportType = (typeof REPORT_TYPES)[number]["value"];

export interface RunDraft {
  topic: string;
  context: string;
  reportType: ReportType;
}

interface Attachment {
  name: string;
  size: number;
  text: string;
}

interface RunComposerProps {
  starting?: boolean;
  defaultReportType?: ReportType;
  onStart: (draft: RunDraft) => void;
  submitLabel?: string;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function RunComposer({
  starting = false,
  defaultReportType = "auto",
  onStart,
  submitLabel = "Start run",
}: RunComposerProps) {
  // A draft survives a detour through the login page.
  const initialDraft = useMemo(() => loadDraft(), []);
  const initialType = REPORT_TYPES.find((option) => option.value === initialDraft?.reportType);
  const [topic, setTopic] = useState(initialDraft?.topic ?? "");
  const [manual, setManual] = useState(initialDraft?.context ?? "");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [reportType, setReportType] = useState<ReportType>(initialType?.value ?? defaultReportType);
  const [dragging, setDragging] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    saveDraft({ topic, context: manual, reportType });
  }, [topic, manual, reportType]);

  const { context, truncated } = useMemo(() => {
    let value = manual.trim();
    let cut = false;
    for (const file of attachments) {
      const block = `\n\n--- ${file.name} ---\n${file.text.trim()}`;
      if (value.length + block.length > MAX_CONTEXT) {
        value = (value + block).slice(0, MAX_CONTEXT);
        cut = true;
        break;
      }
      value += block;
    }
    return { context: value.slice(0, MAX_CONTEXT), truncated: cut };
  }, [manual, attachments]);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setExtracting(true);

    for (const file of Array.from(files)) {
      const lower = file.name.toLowerCase();
      if (file.size > MAX_FILE_BYTES) {
        toast.error(`${file.name} is larger than 10 MB.`);
        continue;
      }

      try {
        let text: string;
        if (lower.endsWith(".pdf")) {
          text = await extractPdfText(file);
        } else if (
          TEXT_TYPES.some((ext) => lower.endsWith(ext)) ||
          file.type.startsWith("text/")
        ) {
          text = await file.text();
        } else {
          toast.error(`${file.name} isn't a PDF, TXT or MD file.`);
          continue;
        }

        if (!text.trim()) {
          toast.error(`No text found in ${file.name}.`);
          continue;
        }

        setAttachments((current) => [
          ...current.filter((item) => item.name !== file.name),
          { name: file.name, size: file.size, text },
        ]);
        toast.success(`Added ${file.name}`);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `Couldn't read ${file.name}.`);
      }
    }

    setExtracting(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  const topicFilled = topic.trim().length > 0;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!topicFilled || starting) return;
        onStart({ topic: topic.trim(), context, reportType });
      }}
      className="flex flex-col gap-4 text-left"
    >
      <section className="rounded-2xl border border-line bg-surface">
        <div className="flex items-center justify-between px-6 pb-4 pt-5">
          <h2 className="text-base font-semibold text-fg">Topic</h2>
          <span className="text-xs text-muted">Max 300 characters</span>
        </div>
        <div className="border-t border-line" />
        <div className="p-6">
          <input
            autoFocus
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="What should this report be about?"
            maxLength={300}
            className="h-11 w-full rounded-lg border border-line bg-bg px-4 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
          />

          <textarea
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            placeholder="Paste any background material here..."
            rows={4}
            className="mt-4 w-full resize-y rounded-lg border border-line bg-bg px-4 py-3 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
          />

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              void handleFiles(event.dataTransfer.files);
            }}
            className={`mt-4 rounded-lg border border-dashed p-4 transition-colors ${
              dragging ? "border-accent bg-accent-soft" : "border-line bg-bg"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="inline-flex items-center gap-2 text-sm text-fg">
                {extracting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Upload className="h-4 w-4" aria-hidden="true" />
                )}
                {extracting ? "Extracting text…" : "Drop PDFs or text files here"}
              </span>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:bg-accent-soft"
              >
                Browse files
              </button>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.md,.markdown,text/plain,application/pdf"
                onChange={(event) => void handleFiles(event.target.files)}
                className="hidden"
              />
            </div>

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <span>PDF and text files are read directly. Scans without text layers cannot be read.</span>
              <span
                className={`tabular-nums ${
                  context.length >= MAX_CONTEXT
                    ? "font-bold text-red-500 dark:text-red-400"
                    : context.length >= MAX_CONTEXT * 0.9
                      ? "font-semibold text-amber-500 dark:text-amber-400"
                      : "text-muted"
                }`}
              >
                {context.length.toLocaleString()} / {MAX_CONTEXT.toLocaleString()}
              </span>
            </div>

            {truncated && (
              <p className="mt-2 text-xs font-medium text-amber-600 dark:text-amber-400">
                Some background text was truncated to stay within the 40,000 character limit.
              </p>
            )}

            {attachments.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2">
                {attachments.map((file) => (
                  <li
                    key={file.name}
                    className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-fg"
                  >
                    <FileText className="h-3 w-3 text-muted" aria-hidden="true" />
                    <span className="max-w-[180px] truncate">{file.name}</span>
                    <span className="text-muted">{formatSize(file.size)}</span>
                    <button
                      type="button"
                      onClick={() =>
                        setAttachments((current) => current.filter((item) => item.name !== file.name))
                      }
                      aria-label={`Remove ${file.name}`}
                      className="text-muted transition-colors hover:text-red-600 dark:hover:text-red-400"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-surface">
        <div className="px-6 pb-4 pt-5">
          <h2 className="text-base font-semibold text-fg">Report type</h2>
          <p className="mt-1 text-sm text-muted">
            This sets the outline, depth, and section targets the planner uses.
          </p>
        </div>
        <div className="border-t border-line" />
        <div className="grid gap-3 p-6 sm:grid-cols-2">
          {REPORT_TYPES.map((option) => {
            const selected = option.value === reportType;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => setReportType(option.value)}
                aria-pressed={selected}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  selected ? "border-accent bg-accent-soft" : "border-line bg-bg hover:border-line-strong"
                }`}
              >
                <span className="block text-sm font-semibold text-fg">{option.label}</span>
                <span className="mt-1 block text-sm leading-6 text-muted">{option.description}</span>
              </button>
            );
          })}
        </div>
      </section>

      <div className="flex flex-col items-end gap-2 sm:flex-row sm:items-center sm:justify-end">
        {!topicFilled && <p className="mr-auto text-xs text-muted">Add a topic to enable Start run.</p>}
        <button
          type="submit"
          disabled={!topicFilled || starting}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0 dark:shadow-[0_10px_30px_-14px_rgba(255,255,255,0.6)]"
        >
          {starting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          )}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
