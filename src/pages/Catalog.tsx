import { useNavigate } from "react-router";
import { ArrowRight, ArrowUpRight, FileText } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { loginUrl, useRequireAuth } from "@/lib/session";

interface CatalogEntry {
  topic: string;
  reportType: string;
  sections: number;
  sources: number;
  blurb: string;
}

const ENTRIES: CatalogEntry[] = [
  {
    topic: "AI meeting summarization tools",
    reportType: "Briefing",
    sections: 6,
    sources: 8,
    blurb: "Real-time versus post-call capture, pricing per seat, and where the audio is processed.",
  },
  {
    topic: "Grid-scale battery storage economics",
    reportType: "Deep dive",
    sections: 9,
    sources: 11,
    blurb: "Duration trends, interconnection queues and the revenue stacks behind new builds.",
  },
  {
    topic: "Postgres versus SQLite for small products",
    reportType: "Briefing",
    sections: 5,
    sources: 7,
    blurb: "Operational cost, concurrency limits and the migration path when a side project grows.",
  },
  {
    topic: "On-device transcription models",
    reportType: "Deep dive",
    sections: 10,
    sources: 9,
    blurb: "Accuracy, latency and privacy trade-offs between local and cloud inference.",
  },
  {
    topic: "EU AI Act obligations for SaaS vendors",
    reportType: "Briefing",
    sections: 6,
    sources: 8,
    blurb: "Risk tiers, documentation duties and what changes for products already in market.",
  },
  {
    topic: "Building an internal research pipeline",
    reportType: "Architecture blueprint",
    sections: 8,
    sources: 6,
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
        "dossier-run-draft",
        JSON.stringify({ topic, context: "", reportType: "auto" }),
      );
    } catch {
      // The draft is a convenience only.
    }
    if (!requireAuth("/runs/new")) return;
    navigate("/runs/new");
  }

  return (
    <div className="px-5 py-10 sm:px-10 sm:py-14">
      <div className="mx-auto max-w-[1080px]">
        <header className="border-b-[1.5px] border-accent pb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted">
            Catalog
          </p>
          <h1 className="mt-4 max-w-[720px] text-[34px] font-bold leading-[1.1] tracking-tight text-fg sm:text-[46px]">
            Example briefs you can start from.
          </h1>
          <p className="mt-4 max-w-[640px] text-base leading-7 text-muted">
            These are the shapes Dossier produces. Pick one to prefill the composer, or write your
            own topic. Every report is built from live sources at the time it runs.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => {
                if (!requireAuth("/runs/new")) return;
                navigate("/runs/new");
              }}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-fg"
            >
              New research run
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
            {user ? (
              <button
                type="button"
                onClick={() => navigate("/runs")}
                className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-muted transition-colors hover:text-fg"
              >
                View my runs
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
              className="flex flex-col justify-between rounded-2xl border border-line bg-surface p-6"
            >
              <div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1">
                    <FileText className="h-3 w-3" aria-hidden="true" />
                    {entry.reportType}
                  </span>
                  <span>{entry.sections} sections</span>
                  <span aria-hidden="true">·</span>
                  <span>{entry.sources} sources</span>
                </div>
                <h2 className="mt-3 text-lg font-semibold tracking-tight text-fg">{entry.topic}</h2>
                <p className="mt-2 text-sm leading-6 text-muted">{entry.blurb}</p>
              </div>

              <button
                type="button"
                onClick={() => startWith(entry.topic)}
                className="mt-5 inline-flex items-center gap-1.5 self-start text-sm font-medium text-accent hover:underline"
              >
                Use this topic
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
    </div>
  );
}
