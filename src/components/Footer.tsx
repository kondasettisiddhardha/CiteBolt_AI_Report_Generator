import { Link } from "react-router-dom";
import Wordmark from "@/components/Wordmark";

export default function Footer({ className = "" }: { className?: string }) {
  return (
    <footer
      className={`mt-auto shrink-0 border-t border-line py-6 text-xs text-muted ${className}`}
    >
      <div className="mx-auto flex w-full max-w-[1040px] flex-wrap items-center justify-between gap-4 px-4 sm:px-8">
        <div className="flex items-center gap-2">
          <span>CiteBolt © 2026</span>
        </div>
        <nav className="flex items-center gap-4">
          <Link to="/privacy" className="transition-colors hover:text-fg">
            Privacy
          </Link>
          <Link to="/terms" className="transition-colors hover:text-fg">
            Terms
          </Link>
          <Link to="/examples" className="transition-colors hover:text-fg">
            Examples
          </Link>
          <Link to="/contact" className="transition-colors hover:text-fg">
            Contact
          </Link>
        </nav>
      </div>
    </footer>
  );
}
