import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import Sidebar from "@/components/Sidebar";

const NO_BACK_PATHS = ["/", "/workspace"];

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const showBack = !NO_BACK_PATHS.includes(location.pathname);

  return (
    <div className="flex min-h-screen bg-[var(--bg)] text-[var(--fg)]">
      <Sidebar />
      <main className="min-w-0 flex-1 pt-14 lg:pt-0">
        <div className="page-container mx-auto w-full max-w-[1040px] px-4 py-6 sm:px-8 sm:py-8">
          {showBack && (
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="group mb-5 inline-flex items-center gap-2 text-[14px] font-medium text-[var(--muted)] transition-colors hover:text-[var(--fg)]"
              aria-label="Go back"
            >
              <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-0.5" />
              <span>Back</span>
            </button>
          )}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
