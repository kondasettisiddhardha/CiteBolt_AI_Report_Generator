import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router";
import { useAuth } from "@/hooks/useAuth";

/** Session helpers shared by the login page, the composer and the shell. */

const DRAFT_KEY = "citebolt-run-draft";
const LEGACY_DRAFT_KEY = "citebolt-run-draft";

export interface RunDraftSnapshot {
  topic: string;
  context: string;
  reportType: string;
  length?: any;
  outline?: any;
  template_outline?: any;
  front_matter?: any;
}

export function saveDraft(draft: RunDraftSnapshot): void {
  try {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // Private mode or a full quota: the draft is a convenience, not required.
  }
}

export function loadDraft(): RunDraftSnapshot | null {
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY) || window.sessionStorage.getItem(LEGACY_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RunDraftSnapshot>;
    if (typeof parsed.topic !== "string") return null;
    return {
      topic: parsed.topic,
      context: typeof parsed.context === "string" ? parsed.context : "",
      reportType: typeof parsed.reportType === "string" ? parsed.reportType : "auto",
      length: parsed.length,
      template_outline: parsed.template_outline ?? parsed.outline,
      front_matter: parsed.front_matter,
    };
  } catch {
    return null;
  }
}

export function clearDraft(): void {
  try {
    window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // ignore
  }
}

export function useRequireAuth() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  /** Returns true when signed in; otherwise sends the visitor to /login?next=… */
  return useCallback(
    (next?: string) => {
      if (user) return true;
      navigate(loginUrl(next ?? location.pathname + location.search));
      return false;
    },
    [user, navigate, location.pathname, location.search],
  );
}

/** `/login?next=<path>` for a page the visitor needs an account to use. */
export function loginUrl(next?: string): string {
  if (!next) return "/login";
  return `/login?next=${encodeURIComponent(next)}`;
}

/** Only allow same-site paths in `next`, never an off-site redirect. */
export function safeNext(value: string | null): string {
  if (!value) return "/workspace";
  if (!value.startsWith("/") || value.startsWith("//")) return "/workspace";
  return value;
}
