import {
  RouterProvider,
  createBrowserRouter,
  useLocation,
  Navigate,
} from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import AppShell from "@/components/AppShell";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Workspace from "@/pages/Workspace";
import NewRun from "@/pages/NewRun";
import RunProgress from "@/pages/RunProgress";
import Runs from "@/pages/Runs";
import Settings from "@/pages/Settings";
import Contact from "@/pages/Contact";
import Approach from "@/pages/Approach";
import Catalog from "@/pages/Catalog";
import { Privacy, Terms } from "@/pages/Legal";
import NotFound from "@/pages/NotFound";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-muted">Loading…</div>
    );
  }

  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <>{children}</>;
}

export default function App() {
  const router = createBrowserRouter([
    {
      path: "/login",
      element: <Login />,
    },
    {
      element: <AppShell />,
      children: [
        { index: true, element: <Landing /> },
        { path: "/workspace", element: <Workspace /> },
        { path: "/catalog", element: <Catalog /> },
        { path: "/approach", element: <Approach /> },
        { path: "/privacy", element: <Privacy /> },
        { path: "/terms", element: <Terms /> },
        { path: "/contact", element: <Contact /> },
        { path: "/runs/new", element: <NewRun /> },
        {
          path: "/runs",
          element: (
            <RequireAuth>
              <Runs />
            </RequireAuth>
          ),
        },
        {
          path: "/runs/:id",
          element: (
            <RequireAuth>
              <RunProgress />
            </RequireAuth>
          ),
        },
        {
          path: "/settings",
          element: (
            <RequireAuth>
              <Settings />
            </RequireAuth>
          ),
        },
        { path: "*", element: <NotFound /> },
      ],
    },
  ]);

  return <RouterProvider router={router} />;
}
