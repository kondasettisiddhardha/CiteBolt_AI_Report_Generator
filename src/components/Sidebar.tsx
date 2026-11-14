import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  FilePlus2,
  FolderOpen,
  History,
  LayoutDashboard,
  LogIn,
  LogOut,
  Mail,
  Menu,
  Settings,
  X,
} from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import Wordmark from "@/components/Wordmark";
import { useCollapse } from "@/hooks/useCollapse";
import { useAuth } from "@/hooks/useAuth";
import { useRuns } from "@/hooks/useRuns";
import { getStoredTheme, setStoredTheme, watchSystemTheme, type ThemePreference } from "@/lib/theme";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
}

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { collapsed, setCollapsed } = useCollapse();
  const [theme, setTheme] = useState<ThemePreference>(getStoredTheme);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [runsExpanded, setRunsExpanded] = useState(true);

  // Fetch recent 5 runs if signed in
  const { runs } = useRuns({ limit: 5, enabled: !!user });

  useEffect(() => {
    return watchSystemTheme(() => {
      if (getStoredTheme() === "system") {
        setTheme("system");
      }
    });
  }, []);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const handleThemeChange = (next: ThemePreference) => {
    setTheme(next);
    setStoredTheme(next);
  };

  const handleSignOut = async () => {
    await logout();
    navigate("/login");
  };

  const isItemActive = (to: string) => {
    if (to === "/") return location.pathname === "/";
    if (to === "/runs/new") return location.pathname === "/runs/new";
    if (to === "/runs") {
      return (
        location.pathname === "/runs" ||
        (location.pathname.startsWith("/runs/") && location.pathname !== "/runs/new")
      );
    }
    return location.pathname === to;
  };

  const renderNavLink = (item: NavItem) => {
    const Icon = item.icon;
    const isActive = isItemActive(item.to);

    return (
      <NavLink
        key={item.to}
        to={item.to}
        title={collapsed ? item.label : undefined}
        aria-label={item.label}
        className={`group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium transition-colors ${
          collapsed ? "justify-center" : ""
        } ${
          isActive
            ? "bg-[var(--sidebar-active-bg)] text-[var(--fg)] font-semibold"
            : "text-[var(--muted)] hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--fg)]"
        }`}
      >
        {isActive && (
          <span
            className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-[var(--accent)]"
            aria-hidden="true"
          />
        )}
        <Icon className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
        {!collapsed && <span className="truncate">{item.label}</span>}
      </NavLink>
    );
  };

  // Nav Groups definitions:
  // For guests: show Home, Approach, Catalog in upper groups; Contact in bottom group.
  const groupA: NavItem[] = user
    ? [
        { to: "/", label: "Home", icon: LayoutDashboard },
        { to: "/runs/new", label: "New research run", icon: FilePlus2 },
        { to: "/runs", label: "Recent runs", icon: History },
      ]
    : [{ to: "/", label: "Home", icon: LayoutDashboard }];

  const groupB: NavItem[] = [
    { to: "/approach", label: "Approach", icon: Compass },
    { to: "/catalog", label: "Catalog", icon: FolderOpen },
  ];

  const groupC: NavItem[] = user
    ? [
        { to: "/settings", label: "Settings", icon: Settings },
        { to: "/contact", label: "Contact", icon: Mail },
      ]
    : [{ to: "/contact", label: "Contact", icon: Mail }];

  return (
    <>
      {/* Mobile Top Bar */}
      <div className="fixed top-0 left-0 right-0 z-30 flex h-14 items-center justify-between border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] px-4 lg:hidden">
        <NavLink to="/" className="flex items-center gap-2">
          <img src="/logo.svg" className="h-7 w-7 shrink-0 rounded-lg" alt="" />
          <Wordmark size="md" />
        </NavLink>
        <div className="flex items-center gap-2">
          <ThemeToggle mode={theme} onChange={handleThemeChange} />
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--sidebar-border)] text-[var(--fg)]"
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-screen max-h-screen flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] transition-all duration-200 lg:static ${
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        } ${collapsed ? "lg:w-16" : "lg:w-60"} w-64`}
      >
        {/* 1. Header: Logo + Wordmark + Collapse button */}
        <div
          className={`flex h-14 shrink-0 items-center border-b border-[var(--sidebar-border)] px-3 ${
            collapsed ? "justify-center" : "justify-between"
          }`}
        >
          <NavLink
            to="/"
            className="flex items-center gap-2.5 overflow-hidden"
            title={collapsed ? "Citebolt home" : undefined}
            aria-label="Citebolt home"
          >
            <img src="/logo.svg" className="h-7 w-7 shrink-0 rounded-lg" alt="" />
            {!collapsed && <Wordmark size="md" />}
          </NavLink>

          {/* Desktop collapse toggle */}
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="hidden h-7 w-7 items-center justify-center rounded-md border border-[var(--sidebar-border)] text-[var(--muted)] hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--fg)] lg:flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>

          {/* Mobile close button */}
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            aria-label="Close menu"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted)] hover:text-[var(--fg)] lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable Navigation Area */}
        <div className="flex flex-1 flex-col overflow-y-auto p-2" aria-label="Main Navigation">
          {/* 2. Group A (main): Home, New research run, Recent runs */}
          <div className="space-y-1">
            {groupA.map((item) => {
              if (item.to === "/runs" && user) {
                const isActive = isItemActive("/runs");
                return (
                  <div key="/runs">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">{renderNavLink(item)}</div>
                      {!collapsed && runs.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setRunsExpanded(!runsExpanded)}
                          className="mr-1 inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:text-[var(--fg)]"
                          aria-label={runsExpanded ? "Collapse recent runs" : "Expand recent runs"}
                        >
                          <ChevronDown
                            className={`h-3.5 w-3.5 transition-transform ${
                              runsExpanded ? "rotate-0" : "-rotate-90"
                            }`}
                          />
                        </button>
                      )}
                    </div>

                    {/* Expandable list of the last 5 runs */}
                    {runsExpanded && runs.length > 0 && !collapsed && (
                      <div className="ml-7 mt-1 space-y-0.5 border-l border-[var(--sidebar-border)] pl-2">
                        {runs.slice(0, 5).map((r) => {
                          const isRunActive = location.pathname === `/runs/${r.id}`;
                          return (
                            <NavLink
                              key={r.id}
                              to={`/runs/${r.id}`}
                              title={r.title || r.topic}
                              className={`block truncate rounded px-2 py-1 text-xs transition-colors ${
                                isRunActive
                                  ? "bg-[var(--sidebar-active-bg)] font-semibold text-[var(--accent)]"
                                  : "text-[var(--muted)] hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--fg)]"
                              }`}
                            >
                              {r.title || r.topic}
                            </NavLink>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              }
              return renderNavLink(item);
            })}
          </div>

          {/* 3. Thin divider */}
          <div className="my-2.5 border-t border-[var(--sidebar-border)]" aria-hidden="true" />

          {/* 4. Group B (info): Approach, Catalog */}
          <div className="space-y-1">{groupB.map(renderNavLink)}</div>

          {/* 5. Flexible spacer pushing bottom groups */}
          <div className="min-h-4 flex-1" />

          {/* 6. Thin divider */}
          <div className="my-2.5 border-t border-[var(--sidebar-border)]" aria-hidden="true" />

          {/* 7. Group C (bottom): Settings, Contact */}
          <div className="space-y-1">{groupC.map(renderNavLink)}</div>
        </div>

        {/* 8. Thin divider */}
        <div className="border-t border-[var(--sidebar-border)]" aria-hidden="true" />

        {/* 9. User footer: Account email, theme toggle, and Sign out / Sign in */}
        <div className="shrink-0 p-2">
          <div
            className={`flex items-center rounded-lg px-2.5 py-1.5 text-xs text-[var(--muted)] ${
              collapsed ? "justify-center" : "justify-between"
            }`}
          >
            {collapsed ? (
              <span
                className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--sidebar-active-bg)] text-[11px] font-semibold text-[var(--fg)] uppercase"
                title={user ? user.email : "Guest"}
                aria-label={user ? user.email : "Guest"}
              >
                {user ? user.email[0] : "G"}
              </span>
            ) : (
              <div className="min-w-0 flex-1 pr-2">
                <p className="truncate font-medium text-[var(--fg)]" title={user?.email ?? "Guest"}>
                  {user ? user.email : "Browsing as guest"}
                </p>
                <p className="text-[11px] text-[var(--muted)]">
                  {user ? "Active session" : "Read-only"}
                </p>
              </div>
            )}
            {!collapsed && <ThemeToggle mode={theme} onChange={handleThemeChange} />}
          </div>

          {/* Sign out or Sign in button */}
          <div className="mt-1">
            {user ? (
              <button
                type="button"
                onClick={handleSignOut}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-red-500 ${
                  collapsed ? "justify-center" : ""
                }`}
                title={collapsed ? "Sign out" : undefined}
                aria-label="Sign out"
              >
                <LogOut className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                {!collapsed && <span>Sign out</span>}
              </button>
            ) : (
              <NavLink
                to="/login"
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--accent)] ${
                  collapsed ? "justify-center" : ""
                }`}
                title={collapsed ? "Sign in" : undefined}
                aria-label="Sign in"
              >
                <LogIn className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                {!collapsed && <span>Sign in</span>}
              </NavLink>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
