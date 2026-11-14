import { Link, useNavigate } from "react-router";
import { ArrowRight, FileText, Layers, Search, Sparkles, Check } from "lucide-react";
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

  const caption = "Research, distilled.";
  const heading = (
    <h1 className="page-title tracking-tight">
      Turn a topic{" "}
      <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--fg)] to-[var(--accent)]">
        into a report
      </span>
      {" "}you can use.
    </h1>
  );
  const lead = (
    <p className="page-lead">
      Give Dossier a question. It searches, gathers sources, and writes a cited report.
      The result is yours to export, cite, and keep.
    </p>
  );

  return (
    <section className="page-container page-header">
      {/* Desktop (>1024) hides header wordmark + sign-in button, shown by sidebar. */}
      <header className="mx-auto mb-6 flex w-fit max-w-[1040px] items-center justify-between gap-3 rounded-lg px-4 py-2 text-sm bg-[var(--surface)] text-[var(--muted)] outline-none dark:outline-[1px_solid_var(--line)] sm:mx-0 sm:bg-transparent sm:shadow-none sm:text-[var(--muted)]"
        style={{ boxShadow: "0 1px 2px rgba(12,12,13,0.04), 0 6px 18px -12px rgba(12,12,13,0.12)" }}>
        <Link to="/" className="inline-flex items-center gap-2 text-[var(--muted)] hover:text-[var(--fg)]">
          <span className="text-[15px] font-semibold tracking-[0.18em]">DOSSIER</span>
        </Link>
        {user && (
          <button
            type="button"
            onClick={() => navigate("/workspace")}
            className="inline-flex items-center gap-2 text-[var(--muted)] hover:text-[var(--fg)]"
          >
            Workspace
            <ArrowRight className="w-4 h-4 shrink-0" aria-hidden="true" />
          </button>
        )}
      </header>

      <div className="mx-auto pt-8 sm:pt-14">
        <h2 className="eyebrow tracking-[0.2em] uppercase text-[var(--muted)]">{caption}</h2>
        <h1 className="mt-3 page-title">{heading}</h1>
        <p className="mt-3 page-lead">{lead}</p>

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => {
              if (!requireAuth("/runs/new")) return;
              navigate("/runs/new");
            }}
            className="button primary"
          >
            Start a research run
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
          <Link to="/approach" className="button ghost">
            How it works
          </Link>
        </div>
      </div>

      <div className="mt-14 grid grid-cols-3 gap-3 sm:gap-6">
        {Steps.map((step, index) => (
          <article key={index} className="card p-4 sm:p-6">
            <span className="card-icon">
              <step.icon className="w-4 h-4" aria-hidden="true" />
            </span>
            <h3 className="mt-4 text-base font-semibold leading-snug">
              {index + 1}. {step.label}
            </h3>
            <p className="mt-2 text-sm text-[var(--muted)]">{step.guide}</p>
          </article>
        ))}
      </div>

      <div className="mt-10 sm:mt-14 card p-5 sm:p-8">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--muted)]">Sample report</p>
          <span className="rounded-full bg-emerald-50 px-2.5 py-0.75 text-xs font-medium text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300">
            Completed
          </span>
        </div>
        <h2 className="mt-4 text-xl font-semibold tracking-tight">
          Grid-scale battery storage in 2026
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">A cited briefing, 6 sections</p>
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-[var(--muted)]">
          <p>
            <strong className="text-[var(--fg)]">Executive summary.</strong> Storage costs per kWh
            have fallen sharply while deployment has shifted from a handful of markets to most
            of the grid.
          </p>
          <p>
            <strong className="text-[var(--fg)]">Key findings.</strong> Duration is trending from two
            hours to four; interconnection queues, not cell supply, are now the bottleneck.
          </p>
          <p className="text-xs">
            Sources: [1] IEA Storage Outlook · [2] LBNL Utility-Scale Battery Report · [3] NREL Cost
            Projections …
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate("/runs/new")}
          className="mt-5 button ghost"
        >
          <Sparkles className="w-4 h-4" aria-hidden="true" />
          Write your own
        </button>
      </div>


      <footer className="mt-10 sm:mt-14 border-t border-[var(--line)] pt-5 text-xs text-[var(--muted)]">
        <div className="flex flex-wrap items-center gap-4">
          <span>© {new Date().getFullYear()} Dossier</span>
          <nav className="flex items-center gap-4">
            <Link to="/privacy" className="hover:text-[var(--fg)]">Privacy</Link>
            <Link to="/terms" className="hover:text-[var(--fg)]">Terms</Link>
            <Link to="/contact" className="hover:text-[var(--fg)]">Contact</Link>
          </nav>
          <p className="text-xs">v1.0</p>
        </div>
      </footer>
    </section>
  );
}
