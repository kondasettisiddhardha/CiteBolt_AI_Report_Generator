import { useNavigate } from "react-router-dom";
import { ArrowRight, ArrowUpRight, FileText } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { loginUrl, useRequireAuth } from "@/lib/session";

interface CatalogEntry {
  topic: string;
  reportType: string;
  sections: number;
  blurb: string;
}

const ENTRIES: CatalogEntry[] = [
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

export default function Catalog() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const requireAuth = useRequireAuth();

  function startWith(topic: string) {
    try {
      window.sessionStorage.setItem(
        "citebolt-run-draft",
        JSON.stringify({ topic, context: "", reportType: "auto" }),
      );
    } catch {
      // The draft is a convenience only.
    }
    if (!requireAuth("/runs/new")) return;
    navigate("/runs/new");
  }

  return (
    <div className="text-left">
      <header className="border-b border-line pb-8">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          Catalog
        </p>
        <h1 className="mt-2 text-[28px] font-bold leading-tight tracking-tight text-fg sm:text-[34px]">
          Example briefs you can start from.
        </h1>
        <p className="mt-3 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          These are the shapes Citebolt produces. Pick one to prefill the composer, or write your
          own topic. Every report is built from live sources at the time it runs.
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
          {user ? (
            <button
              type="button"
              onClick={() => navigate("/runs")}
              className="inline-flex h-[42px] items-center gap-2 rounded-lg border border-line bg-card px-4 text-sm font-medium text-muted transition-colors hover:text-fg hover:border-line-strong"
            >
              <span>View my runs</span>
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => navigate(loginUrl("/workspace"))}
              className="text-sm text-muted underline underline-offset-2 hover:text-fg"
            >
              Sign in to see your own runs
            </button>
          )}
        </div>
      </header>

      <ul className="mt-8 grid gap-4 sm:grid-cols-2">
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
              onClick={() => startWith(entry.topic)}
              className="mt-5 inline-flex items-center gap-1.5 self-start text-sm font-medium text-accent hover:underline"
            >
              <span>Use this topic</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-xs leading-6 text-muted">
        Catalog entries are illustrative briefs, not stored reports. A run always fetches its own
        sources, so facts and prices will differ from any previous run on the same topic.
      </p>
    </div>
  );
}
