import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, FileText, Layers, Search } from "lucide-react";
import Wordmark from "@/components/Wordmark";
import { useAuth } from "@/hooks/useAuth";
import { useRequireAuth } from "@/lib/session";

const Steps = [
  {
    icon: Search,
    label: "Research",
    lead: "Finds credible sources across the web.",
    guide: "Curates evidence with live citations, not guesses.",
  },
  {
    icon: Layers,
    label: "Analysis",
    lead: "Reads every source it collected.",
    guide: "Extracts the findings, claims, and contradictions.",
  },
  {
    icon: FileText,
    label: "Reporting",
    lead: "Turns the analysis into text.",
    guide: "Drafts a clean, cited report in seconds.",
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const requireAuth = useRequireAuth();

  return (
    <div className="text-left">
      {/* Eyebrow & Hero Header */}
      <div className="pt-2 sm:pt-6">
        <p className="text-[12px] font-semibold uppercase tracking-[0.2em] text-accent">
          Research, distilled.
        </p>
        <h1 className="mt-3 text-[32px] sm:text-[44px] lg:text-[54px] max-w-[760px] font-bold leading-[1.1] tracking-tight text-fg">
          Turn a topic{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-fg to-accent">
            into a report
          </span>{" "}
          you can use.
        </h1>
        <p className="mt-4 max-w-[640px] text-[16px] sm:text-[17px] leading-relaxed text-muted">
          Give CiteBolt a question. It searches, gathers sources, and writes a cited report.
          The result is yours to export, cite, and keep.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => {
              if (!requireAuth("/runs/new")) return;
              navigate("/runs/new");
            }}
            className="inline-flex h-[42px] items-center gap-2 rounded-lg bg-primary px-5 text-[14px] font-medium text-primary-fg shadow-sm transition hover:-translate-y-px"
          >
            <span>Start a research run</span>
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
          {user && (
            <button
              type="button"
              onClick={() => navigate("/workspace")}
              className="inline-flex h-[42px] items-center gap-1.5 rounded-lg border border-line bg-card px-4 text-[14px] font-medium text-muted transition-colors hover:border-line-strong hover:bg-surface hover:text-fg"
            >
              <span>Workspace</span>
              <ArrowRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* 3 Step Cards */}
      <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-3 sm:gap-6">
        {Steps.map((step, index) => (
          <article key={index} className="rounded-xl border border-line bg-card p-5 sm:p-6 shadow-sm">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-accent/10 text-accent">
              <step.icon className="h-4 w-4" aria-hidden="true" />
            </span>
            <h3 className="mt-4 text-base font-semibold leading-snug text-fg">
              {index + 1}. {step.label}
            </h3>
            <p className="mt-1.5 text-sm text-muted">{step.guide}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
