import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  FileText,
  GraduationCap,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { saveDraft, useRequireAuth } from "@/lib/session";
import { COLLEGE_OUTLINE_TEMPLATE } from "@/lib/collegeTemplate";

interface ExampleEntry {
  topic: string;
  reportType: string;
  sections: number;
  blurb: string;
}

const ENTRIES: ExampleEntry[] = [
  {
    topic: "AI meeting summarization tools",
    reportType: "Briefing",
    sections: 6,
    blurb: "Real-time versus post-call capture, pricing per seat, and where the audio is processed.",
  },
  {
    topic: "Grid-scale battery storage economics",
    reportType: "Deep dive",
    sections: 9,
    blurb: "Duration trends, interconnection queues and the revenue stacks behind new builds.",
  },
  {
    topic: "Postgres versus SQLite for small products",
    reportType: "Briefing",
    sections: 5,
    blurb: "Operational cost, concurrency limits and the migration path when a side project grows.",
  },
  {
    topic: "On-device transcription models",
    reportType: "Deep dive",
    sections: 10,
    blurb: "Accuracy, latency and privacy trade-offs between local and cloud inference.",
  },
  {
    topic: "EU AI Act obligations for SaaS vendors",
    reportType: "Briefing",
    sections: 6,
    blurb: "Risk tiers, documentation duties and what changes for products already in market.",
  },
  {
    topic: "Building an internal research pipeline",
    reportType: "Architecture blueprint",
    sections: 8,
    blurb: "Queue design, source validation, citation storage and export formats.",
  },
];

export default function Examples() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const requireAuth = useRequireAuth();
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    document.title = "Examples — CiteBolt";
  }, []);

  function startWith(entry: ExampleEntry) {
    const normType = entry.reportType.toLowerCase().replace(/\s+/g, "");
    saveDraft({
      topic: entry.topic,
      context: "",
      reportType: normType,
    });
    if (!requireAuth("/runs/new")) return;
    navigate("/runs/new");
  }

  function useCollegeFormat() {
    if (!requireAuth("/runs/new?template=college")) return;
    navigate("/runs/new?template=college");
  }

  return (
    <div className="text-left">
      <header className="border-b border-line pb-8">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          EXAMPLES & FORMATS
        </p>
        <h1 className="mt-2 text-[28px] font-bold leading-tight tracking-tight text-fg sm:text-[34px]">
          Example briefs and structured formats.
        </h1>
        <p className="mt-3 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          Pick a topic to prefill a new research run, or choose an accredited academic format. Every report is built from live sources and user facts when it runs.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => {
              if (!requireAuth("/runs/new")) return;
              navigate("/runs/new");
            }}
            className="inline-flex h-[42px] items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px"
          >
            <span>New research run</span>
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </header>

      {/* Featured Template: College project report format (BE Project Stage) */}
      <section className="mt-8 rounded-2xl border border-line bg-surface p-6 sm:p-7 shadow-sm space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-xs font-semibold text-accent">
                <GraduationCap className="h-3.5 w-3.5" aria-hidden="true" />
                ACADEMIC FORMAT
              </span>
              <span className="text-xs text-muted">11 Chapters · Standard Outline</span>
            </div>
            <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-fg">
              College project report format (BE Project Stage)
            </h2>
            <p className="max-w-[700px] text-sm leading-relaxed text-muted">
              The standard college project report structure: title page, certificate, acknowledgements, abstract, contents, 11 chapters, references and appendices.
            </p>
          </div>

          <button
            type="button"
            onClick={useCollegeFormat}
            className="inline-flex h-[42px] shrink-0 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px"
          >
            <span>Use this format</span>
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* Formatting facts */}
        <div className="rounded-xl border border-line bg-card/60 p-4 space-y-2">
          <span className="text-xs font-bold uppercase tracking-wider text-muted">
            Format Specifications
          </span>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1 font-medium text-fg">
              Times New Roman 12pt
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1 font-medium text-fg">
              1.5 spacing
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1 font-medium text-fg">
              Justified
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1 font-medium text-fg">
              Roman then Arabic page numbers
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1 font-medium text-muted">
              1.5" left margin for binding
            </span>
          </div>
        </div>

        {/* Action toggles: View full outline & View title page preview */}
        <div className="flex flex-wrap items-center gap-4 pt-1 border-t border-line">
          <button
            type="button"
            onClick={() => setOutlineOpen(!outlineOpen)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent hover:underline"
          >
            {outlineOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            <span>{outlineOpen ? "Hide outline" : `View full outline (${COLLEGE_OUTLINE_TEMPLATE.length} sections)`}</span>
          </button>

          <button
            type="button"
            onClick={() => setPreviewOpen(!previewOpen)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent hover:underline"
          >
            {previewOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            <span>{previewOpen ? "Hide title page preview" : "View title page preview"}</span>
          </button>
        </div>

        {/* Expandable outline */}
        {outlineOpen && (
          <div className="max-h-96 overflow-y-auto rounded-xl border border-line bg-bg p-4 space-y-1 text-xs">
            {COLLEGE_OUTLINE_TEMPLATE.map((sec, idx) => (
              <div
                key={idx}
                className={`flex items-center justify-between py-1 px-2.5 rounded ${
                  sec.level === 1
                    ? "font-semibold text-fg"
                    : sec.level === 2
                    ? "pl-6 text-fg/90"
                    : "pl-10 text-muted"
                }`}
              >
                <span className="truncate">
                  {sec.level === 1 && !sec.title.startsWith("Chapter") ? `• ${sec.title}` : sec.title}
                </span>
                <span className="shrink-0 ml-2 font-mono text-[11px] text-muted">
                  {sec.is_auto ? "Auto" : sec.target_words ? `~${sec.target_words} words` : ""}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Title page preview using placeholder text only (no real names) */}
        {previewOpen && (
          <div className="rounded-xl border border-line bg-card p-6 shadow-sm text-center font-serif text-xs sm:text-sm space-y-3 max-w-md mx-auto my-2 text-fg/90">
            <div className="text-sm sm:text-base font-bold tracking-wide uppercase text-fg">
              [PROJECT TITLE IN BOLD CAPITAL LETTERS]
            </div>
            <div className="text-[11px] font-semibold text-muted tracking-wider uppercase">
              A PROJECT REPORT
            </div>
            <div className="text-[11px] sm:text-xs text-muted leading-relaxed">
              Submitted in partial fulfillment of the academic requirements<br />
              for the award of the degree of<br />
              <span className="font-semibold text-fg">BACHELOR OF TECHNOLOGY / ENGINEERING</span>
            </div>
            <div className="pt-2 text-xs">
              <div className="text-[11px] font-semibold text-muted uppercase">Submitted by</div>
              <div className="mt-1 space-y-0.5 text-muted">
                <div>[Student Name 1] (PRN: [Roll / PRN No.])</div>
                <div>[Student Name 2] (PRN: [Roll / PRN No.])</div>
              </div>
            </div>
            <div className="pt-2 text-xs">
              <div className="text-[11px] font-semibold text-muted uppercase">Under the guidance of</div>
              <div className="mt-1 font-medium text-fg">[Project Guide / Supervisor Name]</div>
            </div>
            <div className="pt-2 text-[11px] sm:text-xs text-muted border-t border-line/60">
              <div>Department of [Department Name]</div>
              <div>[College / University Name]</div>
              <div>Academic Year: [YYYY – YYYY]</div>
            </div>
          </div>
        )}
      </section>

      <div className="mt-12">
        <h2 className="text-lg font-bold tracking-tight text-fg">General Research Topics</h2>
        <p className="mt-1 text-sm text-muted">
          Standard exploratory briefings and deep dives on industry and technology topics.
        </p>
      </div>

      <ul className="mt-4 grid gap-4 sm:grid-cols-2">
        {ENTRIES.map((entry) => (
          <li
            key={entry.topic}
            className="flex flex-col justify-between rounded-2xl border border-line bg-surface p-6 shadow-sm"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-card px-2.5 py-1 font-medium">
                  <FileText className="h-3 w-3 text-accent" aria-hidden="true" />
                  {entry.reportType}
                </span>
                <span>Typically {entry.sections} sections</span>
              </div>
              <h2 className="mt-3 text-lg font-semibold tracking-tight text-fg">{entry.topic}</h2>
              <p className="mt-2 text-sm leading-6 text-muted">{entry.blurb}</p>
            </div>

            <button
              type="button"
              onClick={() => startWith(entry)}
              className="mt-5 inline-flex items-center gap-1.5 self-start text-sm font-medium text-accent hover:underline"
            >
              <span>Use this topic</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-xs leading-6 text-muted">
        Example topics are illustrative briefs, not stored reports. A run always fetches its own
        sources, so facts and prices will differ from any previous run on the same topic.
      </p>
    </div>
  );
}
