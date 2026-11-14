import { Link } from "react-router-dom";

function LegalLayout({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="text-left">
      <div className="max-w-[760px]">
        <p className="text-[13px] font-semibold uppercase tracking-[0.2em] text-accent">Legal</p>
        <h1 className="mt-2 text-[28px] font-bold tracking-tight text-fg sm:text-[34px]">{title}</h1>
        <div className="mt-6 space-y-5 text-[15px] leading-relaxed text-muted [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-fg">
          {children}
        </div>
        <footer className="mt-10 flex flex-wrap gap-4 border-t border-line pt-5 text-xs text-muted">
          <Link to="/approach" className="hover:text-fg">
            Approach
          </Link>
          <Link to="/catalog" className="hover:text-fg">
            Catalog
          </Link>
          <Link to="/privacy" className="hover:text-fg">
            Privacy
          </Link>
          <Link to="/terms" className="hover:text-fg">
            Terms
          </Link>
          <Link to="/contact" className="hover:text-fg">
            Contact
          </Link>
        </footer>
      </div>
    </div>
  );
}

export function Privacy() {
  return (
    <LegalLayout title="Privacy Policy">
      <p>
        Citebolt keeps the smallest amount of data needed to run research reports for you. This page
        explains exactly what is stored.
      </p>
      <h2>What we store</h2>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>Your email address, used only to sign you in with a one-time code.</li>
        <li>The topics you research, the generated reports, and their cited sources.</li>
        <li>Basic run metadata: status, timestamps, report type and source counts.</li>
        <li>Any contact message you choose to send us.</li>
      </ul>
      <h2>What we don't store</h2>
      <p>
        We don't store passwords, payment details, or third-party analytics profiles. Sign-in codes
        are stored only as salted hashes and expire after ten minutes.
      </p>
      <h2>Deleting your data</h2>
      <p>
        You can delete any run from the app, or use <strong>Settings → Delete all my runs</strong>{" "}
        to remove every report. To delete your account and email address, contact us and we'll erase
        it on request.
      </p>
      <h2>Third parties</h2>
      <p>
        Reports are generated with a language model and web search provider. Only the topic and the
        material you supply are sent to those providers; your email address is never included.
      </p>
    </LegalLayout>
  );
}

export function Terms() {
  return (
    <LegalLayout title="Terms of Service">
      <p>
        Citebolt generates research reports automatically. Use it as a starting point, not as a
        substitute for your own judgement.
      </p>
      <h2>Acceptable use</h2>
      <ul className="list-disc space-y-1.5 pl-5">
        <li>Don't use the service to break the law or infringe someone else's rights.</li>
        <li>Don't attempt to overload, scrape or reverse engineer the API.</li>
        <li>Each account is limited to a set number of runs per day.</li>
      </ul>
      <h2>Accuracy</h2>
      <p>
        Reports are produced by language models from public sources. They can be incomplete or
        wrong. Verify important claims against the cited sources before relying on them.
      </p>
      <h2>Your content</h2>
      <p>
        You own the topics you submit and the reports generated for you. You are responsible for
        making sure any material you upload is yours to use.
      </p>
      <h2>Changes</h2>
      <p>These terms may change as the product evolves; continued use means you accept updates.</p>
    </LegalLayout>
  );
}
