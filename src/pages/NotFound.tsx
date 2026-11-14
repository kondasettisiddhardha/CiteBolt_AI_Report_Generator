import { Link } from "react-router";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center bg-bg px-6 text-center text-fg">
      <p className="text-[13px] font-medium uppercase tracking-[0.22em] text-muted">404</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">This page doesn't exist.</h1>
      <p className="mt-3 max-w-md text-sm text-muted">
        The link may be old, or the run it pointed to was deleted.
      </p>
      <div className="mt-6 flex gap-2">
        <Link
          to="/workspace"
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-fg"
        >
          Go to workspace
        </Link>
        <Link
          to="/"
          className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted hover:text-fg"
        >
          Home
        </Link>
      </div>
    </div>
  );
}
