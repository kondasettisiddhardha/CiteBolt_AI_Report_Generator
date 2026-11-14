import { useNavigate } from "react-router-dom";
import { ArrowRight, FileText, Layers, Search } from "lucide-react";
import { loginUrl, useRequireAuth } from "@/lib/session";
import { useAuth } from "@/hooks/useAuth";

const AGENTS = [
  {
    step: "01",
    icon: Search,
    name: "Research agent",
    summary: "Finds the evidence, and proves it loads.",
    body: "It searches the web, then fetches every candidate URL. Anything that does not answer with a real page is dropped, and addresses are never guessed or assembled by hand. Duplicate domains are capped so one vendor cannot dominate the source list.",
    details: ["Live search + fetch", "HTTP 200 or discarded", "At most two pages per domain"],
  },
  {
    step: "02",
    icon: Layers,
    name: "Analysis agent",
    summary: "Reads the sources, keeps only what they support.",
    body: "The analysis pass extracts themes, statistics and contradictions, then verifies numeric claims — prices, counts, percentages — against the fetched text. A claim whose figure never appears in the cited page is removed before the writer ever sees it.",
    details: ["Themes and tensions", "Numeric claim checks", "Vendor claims labelled as such"],
  },
  {
    step: "03",
    icon: FileText,
    name: "Writing agent",
    summary: "Writes the report, with the receipts attached.",
    body: "The writer follows a fixed structure: an executive summary, key findings, detailed sections, limitations and a conclusion. Citations are [n] markers tied to the numbered source list, so every reference resolves to a page you can open.",
    details: ["Cited [n] markers", "Limitations section", "Markdown, PDF and Word exports"],
  },
];

export default function Approach() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const requireAuth = useRequireAuth();

  return (
    <div className="text-left">
      <header className="border-b border-line pb-8">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">
          Architecture
        </p>
        <h1 className="mt-2 text-[28px] font-bold leading-tight tracking-tight text-fg sm:text-[34px]">
          Three agents, one rule: nothing gets written that a source cannot back.
        </h1>
        <p className="mt-3 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          Citebolt is a small pipeline, not a chat window. Each agent has one job and hands off a
          verifiable artifact to the next, which is what makes the finished report checkable.
        </p>
      </header>

      <ol className="mt-8 space-y-4">
        {AGENTS.map(({ step, icon: Icon, name, summary, body, details }) => (
          <li
            key={step}
            className="rounded-2xl border border-line bg-surface p-6 sm:p-7 shadow-sm text-left"
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <span className="text-xs font-semibold tracking-wider text-muted uppercase">
                    Agent {step}
                  </span>
                  <h2 className="text-lg font-bold text-fg">{name}</h2>
                </div>
              </div>
            </div>

            <p className="mt-3 text-sm font-semibold text-fg">{summary}</p>
            <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>

            <ul className="mt-4 flex flex-wrap gap-2 border-t border-line/60 pt-4">
              {details.map((detail) => (
                <li
                  key={detail}
                  className="rounded-full border border-line bg-card px-3 py-1 text-xs font-medium text-muted"
                >
                  {detail}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>

      <div className="mt-10 rounded-2xl border border-line bg-card p-6 sm:p-8 shadow-sm">
        <h2 className="text-lg font-bold text-fg">Ready to verify with your own research?</h2>
        <p className="mt-2 max-w-[560px] text-sm text-muted">
          Pick a topic you know well and see how the sources stack up against what the model writes.
        </p>
        <button
          type="button"
          onClick={() => {
            if (!requireAuth("/runs/new")) return;
            navigate("/runs/new");
          }}
          className="mt-5 inline-flex h-[42px] items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-fg shadow-sm transition hover:-translate-y-px"
        >
          <span>Start a run</span>
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
