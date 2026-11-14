import type { ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";

const HOME_PATH = ["/", "/workspace"];

export default function AppShell() {
  const location = useLocation();
  const isHome = HOME_PATH.includes(location.pathname);

  return (
    <div className="flex min-h-screen bg-[var(--bg)] text-[var(--fg)]">
      <Sidebar />
      <main className="min-w-0 flex-1">
        {isHome ? (
          <div className="page-container">
            <Outlet />
          </div>
        ) : (
          <div className="page-container">
            <nav className="mx-auto flex h-12 items-center gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-1 text-xs font-medium text-[var(--muted)]">
              <span className="text-base">←</span>
              <span>Back</span>
            </nav>
            <Outlet />
          </div>
        )}
      </main>
    </div>
  );
}
