import { Link, useNavigate } from "react-router";
import { ArrowRight, FileText, Layers, Search, ShieldCheck } from "lucide-react";
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
    <div className="px-5 py-10 sm:px-10 sm:py-14">
      <div className="mx-auto max-w-[980px]">
        <header className="border-b-[1.5px] border-accent pb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted">
            Approach
          </p>
          <h1 className="mt-4 max-w-[720px] text-[34px] font-bold leading-[1.1] tracking-tight text-fg sm:text-[46px]">
            Three agents, one rule: nothing gets written that a source cannot back.
          </h1>
          <p className="mt-4 max-w-[620px] text-base leading-7 text-muted">
            Dossier is a small pipeline, not a chat window. Each agent has one job and hands off a
            verifiable artifact to the next, which is what makes the finished report checkable.
          </p>
        </header>

        <ol className="mt-10 space-y-4">
          {AGENTS.map(({ step, icon: Icon, name, summary, body, details }) => (
            <li
              key={step}
              className="rounded-2xl border border-line bg-surface p-6 sm:p-7"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-start gap-4">
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-accent-soft text-accent">
                    <Icon className="h-4 w-4" strokeWidth={1.7} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                      Step {step}
                    </p>
                    <h2 className="mt-1 text-xl font-semibold tracking-tight text-fg">{name}</h2>
                    <p className="mt-1 text-sm font-medium text-fg">{summary}</p>
                  </div>
                </div>
              </div>

              <p className="mt-4 max-w-[720px] text-sm leading-7 text-muted">{body}</p>

              <ul className="mt-4 flex flex-wrap gap-2">
                {details.map((detail) => (
                  <li
                    key={detail}
                    className="rounded-full border border-line bg-bg px-2.5 py-1 text-xs text-muted"
                  >
                    {detail}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>

        <section className="mt-10 grid gap-4 sm:grid-cols-[1.4fr_1fr]">
          <div className="rounded-2xl border border-line bg-surface p-6 sm:p-7">
            <div className="flex items-center gap-2 text-accent">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              <h2 className="text-base font-semibold text-fg">What the pipeline refuses to do</h2>
            </div>
            <ul className="mt-4 space-y-2 text-sm leading-7 text-muted">
              <li>· Invent a URL, a statistic or a quotation.</li>
              <li>· Present a vendor's marketing line as independent evidence.</li>
              <li>· Hide the gaps — a Limitations section is always written.</li>
              <li>· Mix up citation numbers: the source list is generated from stored data.</li>
            </ul>
          </div>

          <div className="flex flex-col justify-between rounded-2xl border border-line bg-surface p-6 sm:p-7">
            <div>
              <h2 className="text-base font-semibold text-fg">Run it on your topic</h2>
              <p className="mt-2 text-sm leading-6 text-muted">
                Browsing is open to everyone. An account is only needed to start a run and keep its
                exports.
              </p>
            </div>
            <div className="mt-5 flex flex-col gap-2">
              <button
                type="button"
                onClick={() => {
                  if (!requireAuth("/runs/new")) return;
                  navigate("/runs/new");
                }}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-fg"
              >
                Start a research run
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </button>
              {!user && (
                <Link
                  to={loginUrl()}
                  className="text-center text-xs text-muted underline underline-offset-2 hover:text-fg"
                >
                  Sign in instead
                </Link>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
