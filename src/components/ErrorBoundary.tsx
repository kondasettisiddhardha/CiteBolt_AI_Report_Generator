import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-bg px-6 text-center text-fg">
          <p className="text-[13px] font-medium uppercase tracking-[0.22em] text-muted">Something broke</p>
          <h1 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
            This screen hit an unexpected error.
          </h1>
          <p className="mt-2 max-w-md text-sm text-muted">{this.state.error.message}</p>
          <div className="mt-6 flex gap-2">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-fg"
            >
              Reload
            </button>
            <a
              href="/workspace"
              className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted hover:text-fg"
            >
              Workspace
            </a>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
