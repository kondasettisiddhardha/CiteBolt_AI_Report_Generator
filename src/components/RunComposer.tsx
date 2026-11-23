import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FileText,
  Loader2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { API_BASE } from "@/lib/api";
import { extractPdfInBrowser, extractPdfOnServer } from "@/lib/pdf";
import { loadDraft, saveDraft } from "@/lib/session";
import { useAuth } from "@/hooks/useAuth";
import TemplatePanel, {
  type OutlineSection,
  type CollegeFrontMatter,
} from "@/components/TemplatePanel";
import {
  COLLEGE_OUTLINE_TEMPLATE,
  scaleOutlineWords,
  DEFAULT_COLLEGE_FRONT_MATTER,
  cleanTopicForTitle,
} from "@/lib/collegeTemplate";

export const MAX_CONTEXT = 40000;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

const TEXT_TYPES = [".txt", ".md", ".markdown", ".csv", ".json", ".log"];

export type LengthOption = "short" | "standard" | "long";

export const LENGTH_OPTIONS: Array<{
  value: LengthOption;
  label: string;
  pages: string;
  words: string;
  target: number;
}> = [
  {
    value: "short",
    label: "Short",
    pages: "~5 pages",
    words: "1,500–2,000 words",
    target: 1800,
  },
  {
    value: "standard",
    label: "Standard",
    pages: "~10 pages",
    words: "3,500–4,500 words",
    target: 4000,
  },
  {
    value: "long",
    label: "Long",
    pages: "~20 pages",
    words: "8,000–9,000 words",
    target: 8500,
  },
];

export const REPORT_TYPES = [
  {
    value: "auto",
    label: "Auto",
    description: "The planner picks the shape and length that suits the topic.",
  },
  {
    value: "briefing",
    label: "Briefing",
    description: "5-6 tight sections. Fastest to read.",
  },
  {
    value: "deepdive",
    label: "Deep dive",
    description: "9-11 sections with foundations, theory, and counterarguments.",
  },
  {
    value: "architectureblueprint",
    label: "Architecture blueprint",
    description: "Requirements, components, data flow, trade-offs, and delivery plan.",
  },
] as const;

export type ReportType = (typeof REPORT_TYPES)[number]["value"];

export interface RunDraft {
  topic: string;
  context: string;
  reportType: ReportType;
  length?: LengthOption;
  targetWords?: number;
  template_outline?: OutlineSection[];
  front_matter?: CollegeFrontMatter;
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
}: RunComposerProps) {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const collegeParam = searchParams.get("template") === "college";
  const initialDraft = useMemo(() => loadDraft(), []);
  const initialType = REPORT_TYPES.find((option) => option.value === initialDraft?.reportType);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [topic, setTopic] = useState(initialDraft?.topic ?? "");
  const [isTitleManuallyEdited, setIsTitleManuallyEdited] = useState<boolean>(() => {
    const clean = cleanTopicForTitle(initialDraft?.topic ?? "");
    const draftTitle = initialDraft?.front_matter?.projectTitle?.trim() ?? "";
    if (draftTitle && clean && draftTitle !== clean) {
      return true;
    }
    return false;
  });
  const [cachedCollegeFrontMatter, setCachedCollegeFrontMatter] = useState<CollegeFrontMatter>(() => {
    const base = initialDraft?.front_matter ?? DEFAULT_COLLEGE_FRONT_MATTER;
    const clean = cleanTopicForTitle(initialDraft?.topic ?? "");
    if (!base.projectTitle && clean) {
      return { ...base, projectTitle: clean };
    }
    return base;
  });
  const [manual, setManual] = useState(initialDraft?.context ?? "");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [reportType, setReportType] = useState<ReportType>(initialType?.value ?? defaultReportType);
  const [length, setLength] = useState<LengthOption>(initialDraft?.length ?? "standard");
  const [templateOutline, setTemplateOutline] = useState<OutlineSection[] | undefined>(() => {
    if (initialDraft?.template_outline) return initialDraft.template_outline;
    if (collegeParam) return scaleOutlineWords(COLLEGE_OUTLINE_TEMPLATE, 4000);
    return undefined;
  });
  const [templateName, setTemplateName] = useState<string | undefined>(() => {
    if (initialDraft?.front_matter) return "College project report";
    if (collegeParam) return "College project report";
    return undefined;
  });
  const [frontMatter, setFrontMatter] = useState<CollegeFrontMatter | undefined>(() => {
    const clean = cleanTopicForTitle(initialDraft?.topic ?? "");
    if (initialDraft?.front_matter) {
      if (!initialDraft.front_matter.projectTitle && clean) {
        return { ...initialDraft.front_matter, projectTitle: clean };
      }
      return initialDraft.front_matter;
    }
    if (collegeParam) {
      return { ...DEFAULT_COLLEGE_FRONT_MATTER, projectTitle: clean };
    }
    return undefined;
  });
  const [isCollegeActive, setIsCollegeActive] = useState<boolean>(() => {
    return Boolean(initialDraft?.front_matter) || collegeParam;
  });
  const [extracting, setExtracting] = useState(false);
  const [outlineOpen, setOutlineOpen] = useState(false);

  const handleTopicChange = (newTopic: string) => {
    setTopic(newTopic);
    const clean = cleanTopicForTitle(newTopic);
    if (!isTitleManuallyEdited) {
      setCachedCollegeFrontMatter((prev) => ({
        ...prev,
        projectTitle: clean,
      }));
      setFrontMatter((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          projectTitle: clean,
        };
      });
    }
  };

  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedLengthConfig = LENGTH_OPTIONS.find((l) => l.value === length) ?? LENGTH_OPTIONS[1];
  const targetWords = selectedLengthConfig.target;
  const hasTemplate = Boolean(templateOutline && templateOutline.length > 0);

  useEffect(() => {
    if (searchParams.get("template") === "college" && !isCollegeActive) {
      const scaled = scaleOutlineWords(COLLEGE_OUTLINE_TEMPLATE, targetWords);
      setTemplateOutline(scaled);
      setTemplateName("College project report");
      const clean = cleanTopicForTitle(topic);
      setFrontMatter((prev) => {
        const base = prev ?? cachedCollegeFrontMatter ?? DEFAULT_COLLEGE_FRONT_MATTER;
        if (!isTitleManuallyEdited && clean) {
          return { ...base, projectTitle: clean };
        }
        return base;
      });
      setIsCollegeActive(true);
    }
  }, [searchParams, targetWords, isCollegeActive, topic, isTitleManuallyEdited, cachedCollegeFrontMatter]);

  // Save draft state across steps / session
  useEffect(() => {
    saveDraft({
      topic,
      context: manual,
      reportType,
      length,
      template_outline: templateOutline,
      front_matter: frontMatter,
    });
  }, [topic, manual, reportType, length, templateOutline, frontMatter]);

  // Context characters calculation
  const contextChars = useMemo(() => {
    let total = manual.length;
    for (const a of attachments) {
      total += a.text.length + a.name.length + 10;
    }
    return total;
  }, [manual, attachments]);

  // Full joined context
  const fullContext = useMemo(() => {
    let value = manual.trim();
    for (const file of attachments) {
      const block = `\n\n--- ${file.name} ---\n${file.text.trim()}`;
      value += block;
    }
    return value.trim().slice(0, MAX_CONTEXT);
  }, [manual, attachments]);

  // Handle uploaded source files (.pdf, .docx, .txt, .md)
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
        let text = "";
        if (lower.endsWith(".pdf")) {
          try {
            text = await extractPdfInBrowser(file);
          } catch {
            text = await extractPdfOnServer(file);
          }
        } else if (lower.endsWith(".docx")) {
          const res = await fetch(`${API_BASE}/api/extract`, {
            method: "POST",
            credentials: "include",
            headers: {
              "Content-Type":
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "X-Filename": encodeURIComponent(file.name),
            },
            body: await file.arrayBuffer(),
          });
          if (!res.ok) {
            const payload = await res.json().catch(() => null);
            throw new Error(payload?.detail || `Couldn't read text from ${file.name}`);
          }
          const data = await res.json();
          text = data.text || "";
        } else if (
          TEXT_TYPES.some((ext) => lower.endsWith(ext)) ||
          file.type.startsWith("text/")
        ) {
          text = await file.text();
        } else {
          toast.error(`${file.name} is not a .pdf, .txt, .md or .docx file.`);
          continue;
        }

        if (!text.trim()) {
          toast.error(`No text found in ${file.name}.`);
          continue;
        }

        setAttachments((current) => [
          ...current.filter((item) => item.name !== file.name),
          { name: file.name, size: file.size, text: text.trim() },
        ]);
        toast.success(`Added ${file.name}`);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `Couldn't read ${file.name}.`);
      }
    }

    setExtracting(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const removeAttachment = (fileName: string) => {
    setAttachments((current) => current.filter((item) => item.name !== fileName));
  };

  const handleTemplateUpdate = (
    newOutline: OutlineSection[] | undefined,
    newFrontMatter: CollegeFrontMatter | undefined,
    isCollege: boolean,
    name?: string,
  ) => {
    setTemplateOutline(newOutline);
    setFrontMatter(newFrontMatter);
    if (newFrontMatter) {
      setCachedCollegeFrontMatter(newFrontMatter);
    }
    setIsCollegeActive(isCollege);
    setTemplateName(name);
    if (!newOutline && searchParams.get("template") === "college") {
      const next = new URLSearchParams(searchParams);
      next.delete("template");
      setSearchParams(next, { replace: true });
    }
  };

  // Daily runs left logic
  const dailyLimit = user?.daily_limit ?? 10;
  const runsToday = user?.runs_today ?? 0;
  const runsLeft = user?.runs_left ?? Math.max(0, dailyLimit - runsToday);

  // Warnings for Step 3
  const isTopicShort = topic.trim().length > 0 && topic.trim().length < 15;
  const isSourceOverLimit = contextChars > MAX_CONTEXT;
  const isTeamDetailsEmpty =
    isCollegeActive &&
    hasTemplate &&
    (!frontMatter?.projectTitle?.trim() ||
      !frontMatter?.teamMembers?.some((m) => m.name.trim().length > 0));
  const deptVal = (frontMatter?.department || "").trim();
  const univVal = (frontMatter?.university || "").trim();
  const isDeptUnivMixedUp =
    isCollegeActive &&
    Boolean(
      deptVal &&
        (deptVal.toLowerCase().includes("university:") ||
          (!univVal && /\b(?:university|college|institute|polytechnic)\b/i.test(deptVal)))
    );
  const isLongOrTemplate = length === "long" || hasTemplate;
  const isLimitReached = user ? runsLeft <= 0 : false;

  // Estimated token usage based on length and template
  const estimatedTokens = useMemo(() => {
    if (hasTemplate) {
      const sectionCount = templateOutline?.length || 10;
      if (isCollegeActive || sectionCount >= 80) {
        if (length === "short") return { tokens: 35000, label: "~35,000 tokens", isHigh: false };
        if (length === "standard") return { tokens: 75000, label: "~75,000 tokens", isHigh: false };
        return { tokens: 160000, label: "~140,000 – 180,000 tokens", isHigh: true };
      }
      return {
        tokens: Math.round(sectionCount * 1200),
        label: `~${(sectionCount * 1200).toLocaleString()} tokens`,
        isHigh: sectionCount * 1200 > 100000,
      };
    }
    if (length === "short") return { tokens: 5000, label: "~5,000 tokens", isHigh: false };
    if (length === "long") return { tokens: 30000, label: "~30,000 tokens", isHigh: false };
    return { tokens: 15000, label: "~15,000 tokens", isHigh: false };
  }, [hasTemplate, templateOutline, isCollegeActive, length]);

  const isLongCollegeReport =
    (isCollegeActive || (hasTemplate && (templateOutline?.length || 0) > 80)) && length === "long";

  const handleConfirm = () => {
    if (!topic.trim() || starting || isLimitReached) return;
    const finalFrontMatter = isCollegeActive
      ? (frontMatter ?? cachedCollegeFrontMatter)
      : frontMatter;
    onStart({
      topic: topic.trim(),
      context: fullContext,
      reportType,
      length,
      targetWords,
      template_outline: templateOutline,
      front_matter: finalFrontMatter,
    });
  };

  return (
    <div className="mx-auto w-full max-w-[720px] text-left">
      {/* Horizontal Stepper: "1 Topic — 2 Template & Outputs — 3 Review & Confirm" */}
      <nav aria-label="Progress" className="mb-8 border-b border-line pb-4">
        <ol className="flex items-center justify-between text-xs sm:text-sm font-medium">
          <li className="flex items-center">
            <button
              type="button"
              onClick={() => step > 1 && setStep(1)}
              disabled={step === 1}
              className={`transition-colors ${
                step === 1
                  ? "font-semibold text-fg"
                  : step > 1
                  ? "text-muted hover:text-fg cursor-pointer"
                  : "text-muted/60"
              }`}
            >
              <span className={`inline-block pb-1 ${step === 1 ? "border-b-2 border-accent text-fg font-semibold" : ""}`}>
                1 Topic
              </span>
            </button>
          </li>
          <li className="flex-1 flex items-center justify-center px-3" aria-hidden="true">
            <div className="h-px w-full max-w-[80px] bg-line" />
          </li>
          <li className="flex items-center">
            <button
              type="button"
              onClick={() => (step > 2 || topic.trim().length > 0) && setStep(2)}
              disabled={!topic.trim()}
              className={`transition-colors ${
                step === 2
                  ? "font-semibold text-fg"
                  : step > 2
                  ? "text-muted hover:text-fg cursor-pointer"
                  : "text-muted/60 disabled:cursor-not-allowed"
              }`}
            >
              <span className={`inline-block pb-1 ${step === 2 ? "border-b-2 border-accent text-fg font-semibold" : ""}`}>
                2 Template & Outputs
              </span>
            </button>
          </li>
          <li className="flex-1 flex items-center justify-center px-3" aria-hidden="true">
            <div className="h-px w-full max-w-[80px] bg-line" />
          </li>
          <li className="flex items-center">
            <button
              type="button"
              onClick={() => topic.trim().length > 0 && setStep(3)}
              disabled={!topic.trim()}
              className={`transition-colors ${
                step === 3
                  ? "font-semibold text-fg"
                  : "text-muted/60 disabled:cursor-not-allowed"
              }`}
            >
              <span className={`inline-block pb-1 ${step === 3 ? "border-b-2 border-accent text-fg font-semibold" : ""}`}>
                3 Review & Confirm
              </span>
            </button>
          </li>
        </ol>
      </nav>

      {/* STEP 1 — Topic */}
      {step === 1 && (
        <section aria-label="Step 1: Topic" className="space-y-6">
          <div>
            <label htmlFor="topic-input" className="block text-sm font-semibold text-fg">
              Topic <span className="text-red-500">*</span>
            </label>
            <div className="mt-2">
              <input
                id="topic-input"
                autoFocus
                type="text"
                value={topic}
                onChange={(e) => handleTopicChange(e.target.value.slice(0, 300))}
                placeholder="What should this report be about?"
                maxLength={300}
                className="h-11 w-full rounded-lg border border-line bg-surface px-4 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <div className="mt-1 flex justify-end">
                <span className="font-mono text-xs text-muted">{topic.length} / 300</span>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <label htmlFor="source-material" className="block text-sm font-semibold text-fg">
                Source material <span className="font-normal text-muted">(optional)</span>
              </label>
              <span className="font-mono text-xs text-muted">
                {contextChars.toLocaleString()} / 40,000
              </span>
            </div>
            <p className="text-xs text-muted">Facts the report should draw from.</p>

            <textarea
              id="source-material"
              value={manual}
              onChange={(e) => setManual(e.target.value)}
              placeholder="Paste any background material, notes, or articles here..."
              rows={5}
              className="w-full resize-y rounded-lg border border-line bg-surface px-4 py-3 text-sm text-fg placeholder:text-muted focus:border-line-strong focus:outline-none focus:ring-2 focus:ring-ring"
            />

            {/* Compact Add Files button */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={extracting}
                className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg shadow-sm transition hover:border-line-strong hover:bg-surface-hover"
              >
                {extracting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Upload className="h-3.5 w-3.5" />
                )}
                <span>Add files</span>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.md,.markdown,.docx"
                className="hidden"
                onChange={(e) => void handleFiles(e.target.files)}
              />
              <span className="text-[11px] text-muted">.pdf .txt .md .docx up to 10 MB</span>
            </div>

            {/* Attachments Chips */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-2">
                {attachments.map((file) => (
                  <span
                    key={file.name}
                    className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg"
                  >
                    <FileText className="h-3.5 w-3.5 text-muted" />
                    <span className="max-w-[200px] truncate">{file.name}</span>
                    <span className="font-mono text-muted">({formatSize(file.size)})</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(file.name)}
                      className="ml-0.5 text-muted hover:text-fg"
                      aria-label={`Remove ${file.name}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Action Row: Single button "Next", no Skip on step 1 */}
          <div className="flex justify-end pt-2">
            <button
              type="button"
              onClick={() => setStep(2)}
              disabled={!topic.trim()}
              className="inline-flex h-10 items-center justify-center rounded-lg bg-teal-600 px-6 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </section>
      )}

      {/* STEP 2 — Template & Outputs */}
      {step === 2 && (
        <section aria-label="Step 2: Template & Outputs" className="space-y-6">
          {/* Target length: one full-width row of 3 equal cards on desktop, stacked on mobile */}
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-fg">Target length</label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 items-stretch">
              {LENGTH_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setLength(opt.value)}
                  className={`flex flex-col justify-between h-full rounded-lg border p-3.5 text-left transition ${
                    length === opt.value
                      ? "border-accent bg-accent/5 ring-1 ring-accent"
                      : "border-line bg-surface hover:border-line-strong"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-fg">{opt.label}</span>
                      <span className="font-mono text-xs text-muted">{opt.pages}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted leading-relaxed">{opt.words}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Report type: a 2x2 grid of equal-height cards on desktop, one column on mobile */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-semibold text-fg">Report type</label>
              {hasTemplate && (
                <span className="rounded bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
                  Using your template's structure
                </span>
              )}
            </div>
            <div
              className={`grid grid-cols-1 sm:grid-cols-2 gap-3 items-stretch ${
                hasTemplate ? "pointer-events-none opacity-40" : ""
              }`}
            >
              {REPORT_TYPES.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  disabled={hasTemplate}
                  onClick={() => setReportType(opt.value)}
                  className={`flex flex-col justify-between h-full rounded-lg border p-3.5 text-left transition ${
                    reportType === opt.value && !hasTemplate
                      ? "border-accent bg-accent/5 ring-1 ring-accent"
                      : "border-line bg-surface hover:border-line-strong"
                  }`}
                >
                  <div>
                    <span className="text-sm font-semibold text-fg">{opt.label}</span>
                    <p className="mt-1 text-xs leading-relaxed text-muted">{opt.description}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Reference template (optional) panel: full width below with no leftover space */}
          <div className="w-full">
            <TemplatePanel
              topic={topic}
              isTitleManuallyEdited={isTitleManuallyEdited}
              onTitleManualEditChange={setIsTitleManuallyEdited}
              targetTotalWords={targetWords}
              outline={templateOutline}
              frontMatter={frontMatter ?? (isCollegeActive ? cachedCollegeFrontMatter : undefined)}
              isCollegeChipActive={isCollegeActive}
              templateName={templateName}
              onUpdate={handleTemplateUpdate}
            />
          </div>

          {/* Buttons: Back, Skip, Next */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="inline-flex h-10 items-center justify-center rounded-lg border border-line bg-surface px-5 text-sm font-medium text-fg shadow-sm transition hover:bg-surface-hover"
            >
              Back
            </button>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setStep(3)}
                className="text-xs font-medium text-muted hover:text-fg"
              >
                Skip
              </button>
              <button
                type="button"
                onClick={() => setStep(3)}
                className="inline-flex h-10 items-center justify-center rounded-lg bg-teal-600 px-6 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-500"
              >
                Next
              </button>
            </div>
          </div>
        </section>
      )}

      {/* STEP 3 — Review & Confirm */}
      {step === 3 && (
        <section aria-label="Step 3: Review & Confirm" className="space-y-6">
          {/* One compact summary card (not many boxes) */}
          <div className="rounded-xl border border-line bg-surface p-5 space-y-4">
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Topic
              </span>
              <p className="mt-1 text-sm font-semibold text-fg">{topic}</p>
            </div>

            <div className="border-t border-line" />

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <span className="font-semibold text-muted">Source material</span>
                <p className="mt-0.5 text-fg">
                  {attachments.length > 0 ? `${attachments.length} file(s), ` : ""}
                  {contextChars > 0
                    ? `${contextChars.toLocaleString()} / 40,000 chars used`
                    : "None (planner will search live sources)"}
                </p>
              </div>

              <div>
                <span className="font-semibold text-muted">Target Length</span>
                <p className="mt-0.5 text-fg">
                  {selectedLengthConfig.label} ({selectedLengthConfig.pages}, {selectedLengthConfig.words})
                </p>
              </div>

              <div>
                <span className="font-semibold text-muted">Structure & Report Type</span>
                <p className="mt-0.5 text-fg">
                  {hasTemplate
                    ? `${templateName || (isCollegeActive ? "College project report template" : "Reference template")} (${templateOutline?.length} sections)`
                    : `${REPORT_TYPES.find((t) => t.value === reportType)?.label ?? "Auto"} report`}
                </p>
              </div>

              <div>
                <span className="font-semibold text-muted">Estimated LLM Tokens</span>
                <p className="mt-0.5 text-fg flex items-center gap-1.5">
                  <span className="font-mono">{estimatedTokens.label}</span>
                  {estimatedTokens.isHigh && (
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                      High usage
                    </span>
                  )}
                </p>
              </div>

              {hasTemplate && (
                <div>
                  <span className="font-semibold text-muted">Outline word allocation</span>
                  <p className="mt-0.5 text-fg">
                    {(templateOutline ?? []).reduce(
                      (sum, s) => sum + (s.target_words || s.suggested_words || 0),
                      0,
                    ).toLocaleString()}{" "}
                    total words
                  </p>
                </div>
              )}

              <div>
                <span className="font-semibold text-muted">Estimated Token Budget</span>
                <p className="mt-0.5 text-fg font-medium">
                  {estimatedTokens.label}
                </p>
              </div>
            </div>

            {/* Outline preview if template attached (collapsed, expandable) */}
            {hasTemplate && templateOutline && templateOutline.length > 0 && (
              <div className="border-t border-line pt-3">
                <button
                  type="button"
                  onClick={() => setOutlineOpen(!outlineOpen)}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent hover:underline"
                >
                  {outlineOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  <span>
                    {outlineOpen
                      ? "Hide outline"
                      : `Show outline (${templateOutline.length} sections)`}
                  </span>
                </button>

                {outlineOpen && (
                  <div className="mt-2.5 max-h-48 overflow-y-auto rounded-lg border border-line bg-bg p-2 space-y-1 text-xs">
                    {templateOutline.map((sec, idx) => (
                      <div
                        key={idx}
                        className={`flex items-center justify-between px-2 py-1 rounded ${
                          sec.level === 1
                            ? "font-semibold text-fg"
                            : sec.level === 2
                            ? "pl-4 text-fg/90"
                            : "pl-7 text-muted"
                        }`}
                      >
                        <span className="truncate">
                          {idx + 1}. {sec.title}
                        </span>
                        <span className="font-mono text-[11px] text-muted shrink-0 ml-2">
                          {sec.target_words ?? 200}w
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Team details summary if college template */}
            {isCollegeActive && frontMatter && (
              <div className="border-t border-line pt-3 text-xs space-y-1">
                <span className="font-semibold text-muted">College Details Summary</span>
                <p className="text-fg">
                  <span className="text-muted">Title: </span>
                  {frontMatter.projectTitle || "Not specified"}
                </p>
                <p className="text-fg">
                  <span className="text-muted">Members: </span>
                  {frontMatter.teamMembers
                    ?.filter((m) => m.name.trim())
                    .map((m) => `${m.name}${m.prn ? ` (${m.prn})` : ""}`)
                    .join(", ") || "None specified"}
                </p>
                <p className="text-fg">
                  <span className="text-muted">Guide / Dept: </span>
                  {[frontMatter.guide, frontMatter.department, frontMatter.university]
                    .filter(Boolean)
                    .join(" · ") || "Not specified"}
                </p>
              </div>
            )}
          </div>

          {/* Amber one-line warnings only when relevant */}
          <div className="space-y-2">
            {isTopicShort && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>Topic is very brief; adding more detail may produce a better report.</span>
              </div>
            )}

            {isSourceOverLimit && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>Source material exceeds 40,000 characters and will be trimmed.</span>
              </div>
            )}

            {isTeamDetailsEmpty && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  Team details are empty; certificate and title page fields will be left blank.
                </span>
              </div>
            )}

            {isDeptUnivMixedUp && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>Department and University look mixed up</span>
              </div>
            )}

            {isLongCollegeReport && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  <strong>High token estimate ({estimatedTokens.label}):</strong> Long reports with 100+ sections approach Groq free-tier daily limits (200k TPD). The pipeline will automatically switch to fallback models or pause safely with all finished sections saved if limits are reached.
                </span>
              </div>
            )}

            {isLongOrTemplate && !isLongCollegeReport && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>Long reports or custom templates may take 10+ minutes to generate.</span>
              </div>
            )}

            {isLimitReached && (
              <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3.5 py-2 text-xs text-red-700 dark:text-red-300">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>Daily limit reached (0 runs left today). Try again tomorrow.</span>
              </div>
            )}
          </div>

          {/* Daily runs left note */}
          <div className="flex items-center justify-between pt-1">
            <p className="font-mono text-xs text-muted">
              {runsLeft} of {dailyLimit} runs left today
            </p>
          </div>

          {/* Action Buttons: Back and Confirm and generate */}
          <div className="flex items-center justify-between pt-4">
            <button
              type="button"
              onClick={() => setStep(2)}
              disabled={starting}
              className="inline-flex h-10 items-center justify-center rounded-lg border border-line bg-surface px-5 text-sm font-medium text-fg shadow-sm transition hover:bg-surface-hover disabled:opacity-40"
            >
              Back
            </button>

            <button
              type="button"
              onClick={handleConfirm}
              disabled={starting || isLimitReached || !topic.trim()}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-teal-600 px-6 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {starting && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>Confirm and generate</span>
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
