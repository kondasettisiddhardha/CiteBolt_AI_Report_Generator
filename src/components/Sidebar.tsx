import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  FilePlus2,
  History,
  Settings,
  Mail,
  LogOut,
  LogIn,
  FolderOpen,
  Compass,
} from "lucide-react";
import ThemeToggle, { type ThemeMode } from "@/components/ThemeToggle";
import { useCollapse } from "@/hooks/useCollapse";
import type { RunItem } from "@/hooks/useRuns";

const COLLAPSE_KEY = "dossier-sidebar-collapsed";

function SidebarLogo({ collapsed }: { collapsed: boolean }) {
  return (
    <NavLink to="/" className="sidebar-logo" title={collapsed ? "Dossier home" : undefined}>
      <span className="sidebar-logo-mark" aria-hidden="true">D</span>
      {!collapsed && <span className="sidebar-logo-text">DOSSIER</span>}
    </NavLink>
  );
}

function itemIcon({
  icon,
  active,
  collapsed,
}: {
  icon: string;
  active: boolean;
  collapsed: boolean;
}) {
  const base = "text-[18px]";
  const style: Record<string, { to: string; icon: React.JSX.Element; label: string }> = {
    Home: {
      to: "/",
      icon: <LayoutDashboard className={base} aria-hidden="true" />,
      label: "Home",
    },
    New: {
      to: "/runs/new",
      icon: <FilePlus2 className={base} aria-hidden="true" />,
      label: "New research run",
    },
    Recent: {
      to: "/runs",
      icon: <History className={base} aria-hidden="true" />,
      label: "Recent runs",
    },
    Approach: {
      to: "/approach",
      icon: <Compass className={base} aria-hidden="true" />,
      label: "Approach",
    },
    Catalog: {
      to: "/catalog",
      icon: <FolderOpen className={base} aria-hidden="true" />,
      label: "Catalog",
    },
    Settings: {
      to: "/settings",
      icon: <Settings className={base} aria-hidden="true" />,
      label: "Settings",
    },
    Contact: {
      to: "/contact",
      icon: <Mail className={base} aria-hidden="true" />,
      label: "Contact",
    },
  };

  const item = style[icon];
  return (
    <NavLink
      to={item.to}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={({ isActive }: { isActive: boolean }) =>
        `sidebar-link ${isActive ? "sidebar-active" : ""} ${collapsed ? "sidebar-link-collapsed" : ""}`
      }
    >
      <span className="sidebar-link-icon" aria-hidden="true">{item.icon}</span>
      {!collapsed && <span className="sidebar-link-label">{item.label}</span>}
    </NavLink>
  );
}

function SidebarEmail({ collapsed, user, themeMode, setThemeMode }: {
  collapsed: boolean;
  user: { email: string } | null;
  themeMode: ThemeMode;
  setThemeMode: (value: ThemeMode) => void;
}) {
  return (
    <div className="sidebar-user">
      {user ? (
        <span className="sidebar-user-wrap" aria-label="Signed in as ">
          <span className="sidebar-user-email">{user.email}</span>
          {!collapsed && <ThemeToggle mode={themeMode} onChange={setThemeMode} />}
        </span>
      ) : (
        <span className="sidebar-guest">{collapsed ? "Guest" : "Browsing as guest"}</span>
      )}
    </div>
  );
}

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { collapsed, setCollapsed } = useCollapse();
  const [user, setUser] = useState<{ email: string } | null>(null);
  const [themeMode, setThemeMode] = useState<ThemeMode>("light");
  const [mobileOpen, setMobileOpen] = useState(false);
  const isCollapsed = collapsed;

  return (
    <>
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        className="sidebar-toggle-mobile"
        aria-label="Open menu"
        aria-expanded={mobileOpen}
      >
        <svg viewBox="0 0 24 24" className="sidebar-icon" aria-hidden="true">
          <path d="M4 6h16v2H4zM4 12h16v2H4zM4 18h16v2H4z" />
        </svg>
      </button>

      <aside className={`sidebar-wrapper ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar">
          <div className="sidebar-top">
            <SidebarLogo collapsed={isCollapsed} />
            <button
              type="button"
              onClick={() => setCollapsed(!isCollapsed)}
              className="sidebar-toggle"
              aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              <ChevronLeft className="sidebar-toggle-icon" aria-hidden="true" />
              {!isCollapsed && <span className="sidebar-toggle-text">Collapse</span>}
            </button>
          </div>

          <nav className="sidebar-nav" aria-label="Main">
            {itemIcon({
              icon: "Home",
              active: location.pathname === "/",
              collapsed: isCollapsed,
            })}
            {itemIcon({
              icon: "New",
              active: location.pathname === "/runs/new",
              collapsed: isCollapsed,
            })}
            {itemIcon({
              icon: "Recent",
              active: location.pathname.startsWith("/runs"),
              collapsed: isCollapsed,
            })}
            <div className="sidebar-divider" aria-hidden="true" />
            {itemIcon({
              icon: "Approach",
              active: location.pathname === "/approach",
              collapsed: isCollapsed,
            })}
            {itemIcon({
              icon: "Catalog",
              active: location.pathname === "/catalog",
              collapsed: isCollapsed,
            })}
            {itemIcon({
              icon: "Settings",
              active: location.pathname === "/settings",
              collapsed: isCollapsed,
            })}
            {itemIcon({
              icon: "Contact",
              active: location.pathname === "/contact",
              collapsed: isCollapsed,
            })}
          </nav>

          <div className="sidebar-footer">
            <SidebarEmail collapsed={isCollapsed} user={user} themeMode={themeMode} setThemeMode={setThemeMode} />
            <ThemeToggle mode={themeMode} onChange={setThemeMode} />
            <div className="sidebar-divider" aria-hidden="true" />
            <button
              type="button"
              onClick={() => setCollapsed(!isCollapsed)}
              className="sidebar-signout"
              title={isCollapsed ? "Sign out" : undefined}
              aria-label={isCollapsed ? "Sign out" : undefined}
            >
              <LogOut className="sidebar-icon" aria-hidden="true" />
              {!isCollapsed && <span className="sidebar-link-label">Sign out</span>}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
