import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  Compass,
  FilePlus2,
  FolderOpen,
  History,
  LayoutDashboard,
  LogIn,
  LogOut,
  Mail,
  Menu,
  PanelLeft,
  PanelLeftClose,
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

  // Hover state: ONLY triggered from the toggle button at top of collapsed rail
  const [isHovered, setIsHovered] = useState(false);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  const enterTimerRef = useRef<number | null>(null);
  const leaveTimerRef = useRef<number | null>(null);

  // Fetch recent 5 runs
  const { runs } = useRuns({ limit: 5 });

  // Listen for reduced motion preference
  useEffect(() => {
    if (typeof window === "undefined") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(media.matches);
    const listener = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);

  // System theme watch
  useEffect(() => {
    return watchSystemTheme(() => {
      setTheme(getStoredTheme());
    });
  }, []);

  // Close mobile drawer and hover-expanded rail on route change
  useEffect(() => {
    setMobileOpen(false);
    setIsHovered(false);
  }, [location.pathname]);

  // Lock mobile body scroll
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  // Global keyboard shortcut: Ctrl+Shift+S and Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsHovered(false);
      }
      if (
        (e.ctrlKey || e.metaKey) &&
        e.shiftKey &&
        (e.key === "S" || e.key === "s")
      ) {
        const target = e.target as HTMLElement | null;
        if (
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.isContentEditable)
        ) {
          return;
        }
        e.preventDefault();
        setCollapsed((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setCollapsed]);

  // Toggle button hover intent: 120ms enter
  const handleToggleMouseEnter = () => {
    if (leaveTimerRef.current) {
      window.clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
    if (!collapsed) return; // already pinned open
    if (!enterTimerRef.current && !isHovered) {
      enterTimerRef.current = window.setTimeout(() => {
        setIsHovered(true);
        enterTimerRef.current = null;
      }, 120);
    }
  };

  const handleToggleMouseLeave = () => {
    if (enterTimerRef.current) {
      window.clearTimeout(enterTimerRef.current);
      enterTimerRef.current = null;
    }
    if (!collapsed) return;
    scheduleClose();
  };

  // Keyboard focus on toggle button opens the panel
  const handleToggleFocus = () => {
    if (collapsed) {
      setIsHovered(true);
    }
  };

  const handleToggleBlur = (e: React.FocusEvent<HTMLElement>) => {
    if (collapsed && !e.currentTarget.parentElement?.contains(e.relatedTarget as Node | null)) {
      scheduleClose();
    }
  };

  // Floating expanded panel hover handlers: keeps panel open while cursor is inside
  const handlePanelMouseEnter = () => {
    if (leaveTimerRef.current) {
      window.clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
  };

  const handlePanelMouseLeave = () => {
    if (!collapsed) return;
    scheduleClose();
  };

  const scheduleClose = () => {
    if (!leaveTimerRef.current && isHovered) {
      leaveTimerRef.current = window.setTimeout(() => {
        setIsHovered(false);
        leaveTimerRef.current = null;
      }, 250);
    }
  };

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

  // Expanded condition: pinned open, hover-opened from toggle, or mobile drawer open
  const isExpanded = !collapsed || isHovered || mobileOpen;

  const renderNavLink = (item: NavItem) => {
    const Icon = item.icon;
    const isActive = isItemActive(item.to);

    return (
      <NavLink
        key={item.to}
        to={item.to}
        onClick={() => setIsHovered(false)}
        title={!isExpanded ? item.label : undefined}
        aria-label={item.label}
        className={`group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium transition-colors ${
          !isExpanded ? "justify-center" : ""
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
        {isExpanded && <span className="truncate">{item.label}</span>}
      </NavLink>
    );
  };

  // Nav items: Home, New research run, Recent runs always available
  const groupA: NavItem[] = [
    { to: "/", label: "Home", icon: LayoutDashboard },
    { to: "/runs/new", label: "New research run", icon: FilePlus2 },
    { to: "/runs", label: "Recent runs", icon: History },
  ];

  const groupB: NavItem[] = [
    { to: "/approach", label: "Approach", icon: Compass },
    { to: "/examples", label: "Examples", icon: FolderOpen },
  ];

  const groupC: NavItem[] = user
    ? [
        { to: "/settings", label: "Settings", icon: Settings },
        { to: "/contact", label: "Contact", icon: Mail },
      ]
    : [{ to: "/contact", label: "Contact", icon: Mail }];

  return (
    <>
      {/* Mobile Top Bar (under 1024px) */}
      <div className="fixed top-0 left-0 right-0 z-30 flex h-14 items-center justify-between border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] px-4 lg:hidden">
        <NavLink to="/" className="flex items-center gap-2">
          <img src="/logo.svg" className="h-7 w-7 shrink-0 rounded-lg" alt="CiteBolt logo" />
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
        onMouseEnter={handlePanelMouseEnter}
        onMouseLeave={handlePanelMouseLeave}
        className={`fixed inset-y-0 left-0 z-40 flex h-screen h-dvh flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] ${
          prefersReducedMotion
            ? "transition-none"
            : "transition-[width,transform,box-shadow] duration-200 ease-in-out"
        } ${
          mobileOpen
            ? "translate-x-0 w-64 shadow-2xl"
            : "-translate-x-full lg:translate-x-0"
        } ${
          isExpanded
            ? "lg:w-64 " + (collapsed ? "shadow-2xl" : "")
            : "lg:w-16"
        }`}
      >
        {/* 1. Header: Toggle when collapsed; Logo + Wordmark + Toggle when expanded */}
        {!isExpanded ? (
          /* Collapsed rail header: No logo mark before opening sidebar, only the toggle button */
          <div className="flex h-14 shrink-0 items-center justify-center border-b border-[var(--sidebar-border)]">
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              onMouseEnter={handleToggleMouseEnter}
              onMouseLeave={handleToggleMouseLeave}
              onFocus={handleToggleFocus}
              onBlur={handleToggleBlur}
              aria-label="Open sidebar"
              title="Open sidebar (Ctrl+Shift+S)"
              aria-expanded={false}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--sidebar-border)] text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--fg)]"
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          </div>
        ) : (
          /* Expanded state header: Keep logo mark and CITEBOLT wordmark as it is */
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--sidebar-border)] px-3">
            <NavLink
              to="/"
              onClick={() => setIsHovered(false)}
              className="flex items-center gap-2.5 overflow-hidden"
              aria-label="CiteBolt home"
              title="CiteBolt home"
            >
              <img
                src="/logo.svg"
                className="h-7 w-7 shrink-0 rounded-lg"
                alt="CiteBolt logo"
              />
              <Wordmark size="md" />
            </NavLink>

            <div className="flex items-center gap-1">
              {/* Desktop pin / collapse toggle */}
              <button
                type="button"
                onClick={() => setCollapsed(!collapsed)}
                className="hidden h-7 w-7 items-center justify-center rounded-md border border-[var(--sidebar-border)] text-[var(--muted)] hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--fg)] lg:flex"
                aria-expanded={!collapsed || isHovered}
                aria-label={
                  collapsed
                    ? "Pin sidebar (Ctrl+Shift+S)"
                    : "Collapse sidebar (Ctrl+Shift+S)"
                }
                title={
                  collapsed
                    ? "Pin sidebar (Ctrl+Shift+S)"
                    : "Collapse sidebar (Ctrl+Shift+S)"
                }
              >
                <PanelLeftClose className="h-4 w-4" />
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
          </div>
        )}

        {/* Scrollable Navigation Area */}
        <div
          className="flex flex-1 flex-col overflow-y-auto p-2"
          aria-label="Main Navigation"
        >
          {/* Group A (Main): Home, New research run, Recent runs */}
          <div className="space-y-1">
            {groupA.map((item) => {
              if (item.to === "/runs") {
                return (
                  <div key="/runs">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">{renderNavLink(item)}</div>
                      {isExpanded && runs.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setRunsExpanded(!runsExpanded)}
                          className="mr-1 inline-flex h-6 w-6 items-center justify-center rounded text-[var(--muted)] hover:text-[var(--fg)]"
                          aria-label={
                            runsExpanded ? "Collapse recent runs" : "Expand recent runs"
                          }
                          title={
                            runsExpanded ? "Collapse recent runs" : "Expand recent runs"
                          }
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
                    {runsExpanded && runs.length > 0 && isExpanded && (
                      <div className="ml-7 mt-1 space-y-0.5 border-l border-[var(--sidebar-border)] pl-2">
                        {runs.slice(0, 5).map((r) => {
                          const isRunActive = location.pathname === `/runs/${r.id}`;
                          return (
                            <NavLink
                              key={r.id}
                              to={`/runs/${r.id}`}
                              onClick={() => setIsHovered(false)}
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

          {/* Thin divider */}
          <div className="my-2.5 border-t border-[var(--sidebar-border)]" aria-hidden="true" />

          {/* Group B (Info): Approach, Examples */}
          <div className="space-y-1">{groupB.map(renderNavLink)}</div>

          {/* Flexible spacer pushing bottom groups */}
          <div className="min-h-4 flex-1" />

          {/* Thin divider */}
          <div className="my-2.5 border-t border-[var(--sidebar-border)]" aria-hidden="true" />

          {/* Group C (Bottom): Settings, Contact */}
          <div className="space-y-1">{groupC.map(renderNavLink)}</div>
        </div>

        {/* Thin divider */}
        <div className="border-t border-[var(--sidebar-border)]" aria-hidden="true" />

        {/* User footer: Account and Sign out / Sign in */}
        <div className="shrink-0 p-2">
          {!isExpanded ? (
            /* Rail footer: Pinned Account avatar and Sign out/in */
            <div className="flex flex-col items-center gap-2 py-1">
              {/* Account avatar */}
              <span
                className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--sidebar-active-bg)] text-xs font-semibold text-[var(--fg)] uppercase"
                title={user ? user.email : "Guest"}
                aria-label={user ? user.email : "Guest"}
              >
                {user ? user.email[0] : "G"}
              </span>

              {/* Sign out or Sign in icon button */}
              {user ? (
                <button
                  type="button"
                  onClick={handleSignOut}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-red-500"
                  title="Sign out"
                  aria-label="Sign out"
                >
                  <LogOut className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                </button>
              ) : (
                <NavLink
                  to="/login"
                  onClick={() => setIsHovered(false)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--accent)]"
                  title="Sign in"
                  aria-label="Sign in"
                >
                  <LogIn className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                </NavLink>
              )}
            </div>
          ) : (
            /* Expanded footer */
            <div>
              <div className="rounded-lg px-2.5 py-1.5 text-xs text-[var(--muted)]">
                <p className="truncate font-medium text-[var(--fg)]" title={user?.email ?? "Guest"}>
                  {user ? user.email : "Browsing as guest"}
                </p>
                <p className="text-[11px] text-[var(--muted)]">
                  {user ? "Active session" : "Read-only"}
                </p>
              </div>

              {/* Sign out or Sign in button */}
              <div className="mt-1">
                {user ? (
                  <button
                    type="button"
                    onClick={handleSignOut}
                    className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-red-500"
                    title="Sign out"
                    aria-label="Sign out"
                  >
                    <LogOut className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                    <span>Sign out</span>
                  </button>
                ) : (
                  <NavLink
                    to="/login"
                    onClick={() => setIsHovered(false)}
                    className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-[14px] font-medium text-[var(--muted)] transition-colors hover:bg-[var(--sidebar-hover-bg)] hover:text-[var(--accent)]"
                    title="Sign in"
                    aria-label="Sign in"
                  >
                    <LogIn className="h-[18px] w-[18px] shrink-0 text-current" aria-hidden="true" />
                    <span>Sign in</span>
                  </NavLink>
                )}
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
