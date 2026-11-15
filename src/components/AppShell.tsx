import { useState, useEffect } from "react";
import { Outlet, useLocation, useNavigate, NavLink } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import Footer from "@/components/Footer";
import Wordmark from "@/components/Wordmark";
import ThemeToggle from "@/components/ThemeToggle";
import { useCollapse } from "@/hooks/useCollapse";
import { useAuth } from "@/hooks/useAuth";
import {
  getStoredTheme,
  setStoredTheme,
  watchSystemTheme,
  type ThemePreference,
} from "@/lib/theme";

const NO_BACK_PATHS = ["/", "/workspace"];

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { collapsed } = useCollapse();

  const [theme, setTheme] = useState<ThemePreference>(getStoredTheme);

  useEffect(() => {
    return watchSystemTheme(() => {
      setTheme(getStoredTheme());
    });
  }, []);

  const handleThemeChange = (next: ThemePreference) => {
    setTheme(next);
    setStoredTheme(next);
  };

  const showBack = !NO_BACK_PATHS.includes(location.pathname);
  const isLanding = location.pathname === "/";

  return (
    <div className="flex h-screen h-dvh w-full overflow-hidden bg-[var(--bg)] text-[var(--fg)]">
      <Sidebar />
      <main
        className={`min-w-0 flex-1 h-screen h-dvh overflow-y-auto pt-14 lg:pt-0 transition-[padding] duration-200 ${
          collapsed ? "lg:pl-16" : "lg:pl-64"
        }`}
      >
        {/* Slim Top Header on Content Area for ALL Pages (desktop) */}
        <header className="sticky top-0 z-20 hidden lg:flex h-12 w-full items-center justify-between border-b border-[var(--sidebar-border)] bg-[var(--bg)]/90 backdrop-blur-sm px-6 sm:px-8">
          <div className="flex items-center">
            {/* When sidebar is collapsed, show the brand mark and wordmark; when pinned open, hide to avoid duplication */}
            {collapsed ? (
              <NavLink
                to="/"
                className="flex items-center gap-2.5 transition opacity-90 hover:opacity-100"
                aria-label="CiteBolt home"
              >
                <img src="/logo.svg" className="h-6 w-6 shrink-0 rounded-lg" alt="CiteBolt logo" />
                <Wordmark size="sm" />
              </NavLink>
            ) : (
              <div className="h-6" aria-hidden="true" />
            )}
          </div>

          <div className="flex items-center gap-3">
            <ThemeToggle mode={theme} onChange={handleThemeChange} />
            {isLanding && !user && (
              <NavLink
                to="/login"
                className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-xs font-semibold text-primary-fg shadow-sm transition hover:opacity-90"
              >
                Sign in
              </NavLink>
            )}
          </div>
        </header>

        <div className="min-h-full flex flex-col">
          <div className="page-container mx-auto w-full max-w-[1040px] flex-1 px-4 py-6 sm:px-8 sm:py-8 pb-12">
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
          <Footer />
        </div>
      </main>
    </div>
  );
}
